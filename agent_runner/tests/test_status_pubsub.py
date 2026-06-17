"""Unit tests for the Pub/Sub path of status_logger.StatusProgressLogger.

These pin the cloud-native correctness guarantees that a file sink gets for free
but Pub/Sub does not:

  * **Ordering** — the publisher is created with message ordering enabled and every
    event is published under a per-run ordering key, so on-topic order matches the
    order events were emitted (the research-sources-after-slides class of bug).
  * **No lost events** — close() flushes in-flight publishes, which a Cloud Run Job
    needs because it exits the moment the agent finishes.
  * **Ordering self-heal** — a failed publish latches the ordering key closed, so a
    failure must trigger resume_publish or the rest of the run's feed is truncated.
  * **Jobs detection** — Cloud Run *Jobs* set CLOUD_RUN_JOB (not K_SERVICE).

The google-cloud-pubsub client is faked in sys.modules, so these run offline with
no GCP credentials.
"""
import sys
import types as pytypes

import pytest

from agent_runner import status_logger as sl


# ── Fake google.cloud.pubsub_v1 ─────────────────────────────────────────────
class _FakeFuture:
    def __init__(self, exc=None):
        self._exc = exc
        self.resolved = False

    def result(self, timeout=None):
        self.resolved = True
        if self._exc:
            raise self._exc
        return "message-id"

    def add_done_callback(self, cb):
        cb(self)  # fake completes synchronously


class _FakePublisher:
    def __init__(self, publisher_options=None):
        self.publisher_options = publisher_options
        self.published = []          # list of (topic, data, ordering_key)
        self.resumed = []            # list of (topic, ordering_key)
        self.futures = []
        self.fail_next = False

    def publish(self, topic, data, ordering_key=None):
        self.published.append((topic, data, ordering_key))
        fut = _FakeFuture(exc=RuntimeError("boom") if self.fail_next else None)
        self.fail_next = False
        self.futures.append(fut)
        return fut

    def resume_publish(self, topic, ordering_key):
        self.resumed.append((topic, ordering_key))


def _install_fake_pubsub(monkeypatch):
    fake = pytypes.ModuleType("google.cloud.pubsub_v1")
    fake.PublisherClient = _FakePublisher
    fake.types = pytypes.SimpleNamespace(
        PublisherOptions=lambda **kw: dict(kw))
    # Ensure the parent packages resolve, then attach the fake submodule so both
    # `import google.cloud.pubsub_v1` and `from google.cloud import pubsub_v1` work.
    import importlib
    try:
        google_cloud = importlib.import_module("google.cloud")
    except Exception:
        google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
        monkeypatch.setitem(sys.modules, "google", google_mod)
        google_cloud = pytypes.ModuleType("google.cloud")
        monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", fake)
    monkeypatch.setattr(google_cloud, "pubsub_v1", fake, raising=False)
    return fake


@pytest.fixture
def logger_factory(monkeypatch):
    """Build a StatusProgressLogger wired to the fake publisher, with a known run id."""
    _install_fake_pubsub(monkeypatch)
    monkeypatch.setattr(sl, "_RUN_ID", "run_test_123")

    def _make(topic="projects/p/topics/status-progress"):
        return sl.StatusProgressLogger(file_path=None, pubsub_topic=topic)

    return _make


def _last(pub):
    return pub.published[-1]


# ── Ordering ────────────────────────────────────────────────────────────────
def test_publisher_created_with_message_ordering(logger_factory):
    sp = logger_factory()
    assert sp.pubsub_client is not None
    assert sp.pubsub_client.publisher_options == {"enable_message_ordering": True}


def test_publish_uses_run_id_as_ordering_key(logger_factory):
    sp = logger_factory()
    sp.log_status("Designing slide 1 of 3...")
    topic, data, ordering_key = _last(sp.pubsub_client)
    assert ordering_key == "run_test_123"
    assert topic == "projects/p/topics/status-progress"


def test_events_preserve_emission_order_under_one_key(logger_factory):
    sp = logger_factory()
    for msg in ("research", "brief", "slide 1", "slide 2"):
        sp.log_status(msg)
    keys = {ok for (_t, _d, ok) in sp.pubsub_client.published}
    assert keys == {"run_test_123"}  # single key ⇒ ordered stream
    assert len(sp.pubsub_client.published) == 4


# ── Payload shape ───────────────────────────────────────────────────────────
def test_citation_payload_includes_data_and_run_id(logger_factory):
    import json
    sp = logger_factory()
    sp.log_status("Research source captured: illumina.com.",
                  event_type="citation",
                  payload={"name": "Illumina", "url": "https://illumina.com", "domain": "illumina.com"})
    _t, data, _ok = _last(sp.pubsub_client)
    event = json.loads(data.decode("utf-8"))
    assert event["event_type"] == "citation"
    assert event["run_id"] == "run_test_123"
    assert event["data"]["domain"] == "illumina.com"


# ── Ordering self-heal + flush ──────────────────────────────────────────────
def test_failed_publish_resumes_ordering_key(logger_factory):
    sp = logger_factory()
    sp.pubsub_client.fail_next = True
    sp.log_status("an event that fails to publish")
    # The failed future's done-callback must re-open the latched ordering key.
    assert ("projects/p/topics/status-progress", "run_test_123") in sp.pubsub_client.resumed


def test_close_flushes_all_pending_futures(logger_factory):
    sp = logger_factory()
    sp.log_status("one")
    sp.log_status("two")
    futures = list(sp.pubsub_client.futures)
    sp.close()
    assert futures and all(f.resolved for f in futures)
    assert sp._publish_futures == []  # cleared after flush


def test_close_is_safe_without_pubsub():
    sp = sl.StatusProgressLogger(file_path=None, pubsub_topic=None)
    assert sp.pubsub_client is None
    sp.close()  # must not raise


# ── Cloud Run Jobs detection ────────────────────────────────────────────────
def test_in_cloud_run_detects_jobs(monkeypatch):
    for var in ("K_SERVICE", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION"):
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
        monkeypatch.setenv(var, "x")
        assert sl._in_cloud_run() is True, f"{var} should mark a Cloud Run env"


def test_in_cloud_run_false_when_absent(monkeypatch):
    for var in ("K_SERVICE", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION"):
        monkeypatch.delenv(var, raising=False)
    assert sl._in_cloud_run() is False


def test_jobs_env_resolves_default_topic(logger_factory, monkeypatch):
    # On a Job with no explicit topic but a project id, the default topic resolves.
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("CLOUD_RUN_JOB", "ai-builder-agent")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    sp = sl.StatusProgressLogger(file_path=None, pubsub_topic=None)
    assert sp.pubsub_topic == "projects/my-proj/topics/status-progress"
