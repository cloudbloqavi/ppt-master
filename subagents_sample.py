import asyncio
import sys
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

async def main():
    # 1. Configure permissions and capabilities.
    # Subagents automatically inherit these scopes (e.g., file limits and command prefixes)
    capabilities = CapabilitiesConfig(
        allow_terminal_commands=True,
        allowed_prefixes=["python", "pytest", "git"],
        allow_subagent_delegation=True  # Required to let the agent spawn subagents
    )
    
    config = LocalAgentConfig(
        system_instructions=(
            "You are a Senior Project Lead Agent. When given a multi-tier development task, "
            "use the `define_subagent` tool to create specialized subagents (e.g., a TestEngineer "
            "or a TechnicalWriter) to handle parallel components. Coordinate their outputs."
        ),
        capabilities=capabilities
    )
    
    # 2. Initialize the main Agent harness
    print("Initializing Google Antigravity Agent Harness...")
    async with Agent(config) as main_agent:
        
        # 3. Prompt the main agent to execute a task requiring delegation
        prompt = (
            "I need to scaffold a new Python utility. Please write a core mathematics script, "
            "but spin up a dedicated subagent to simultaneously write the pytest unit tests for it. "
            "Merge their results when done."
        )
        
        print(f"\nPrompting Main Agent: '{prompt}'\n")
        response = await main_agent.chat(prompt)
        
        # 4. Stream the live conversational response and subagent logs
        # The background worker sets up an intercepting message client to stream 
        # subagent progress deltas back to your terminal session.
        async for token in response:
            sys.stdout.write(token)
            sys.stdout.flush()
            
        print("\n\n--- Workflow Execution Complete ---")

if __name__ == "__main__":
    # Ensure standard asyncio loop handles the async context managers smoothly
    asyncio.run(main())