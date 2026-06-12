import argparse

from week_02.cli import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Week 02 · Agent Chat with persistent memory")
    parser.add_argument(
        "--user",
        "-u",
        default="default",
        help="user name for persistent history file",
    )
    parser.add_argument(
        "--policy",
        choices=["sliding", "summary"],
        default="sliding",
        help="context policy: sliding window or summary compression",
    )
    args = parser.parse_args()
    run(user=args.user, policy_name=args.policy)
