"""Small example showing how to use GitHubAsyncClient."""
import asyncio
from backend.connectors.github_async_client import GitHubAsyncClient, load_github_config


async def main():
    cfg = load_github_config()
    if not cfg.get("token"):
        print("GITHUB_TOKEN not set; example will not call API.")
        return

    client = GitHubAsyncClient()
    try:
        commits = await client.list_commits("octocat", "Hello-World", per_page=5)
        print(f"Got {len(commits)} commits")

        prs = await client.list_pulls("octocat", "Hello-World", per_page=5)
        print(f"Got {len(prs)} PRs")

        deps = await client.list_deployments("octocat", "Hello-World", per_page=5)
        print(f"Got {len(deps)} deployments")

        runs = await client.list_workflow_runs("octocat", "Hello-World", per_page=5)
        print(f"Got {len(runs)} workflow runs")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
