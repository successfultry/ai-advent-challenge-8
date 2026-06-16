import argparse

from week_03.cli import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Week 03 · Stateful Agent")
    parser.add_argument("--user", "-u", default="default", help="user ID (profiles + tasks)")
    parser.add_argument("--chat", "-c", default="default", help="chat ID (short-term history)")
    parser.add_argument(
        "--fresh",
        "--no-resume",
        action="store_true",
        default=False,
        help="start with empty short-term history (profile + task still loaded from disk)",
    )
    args = parser.parse_args()
    run(user=args.user, chat=args.chat, fresh=args.fresh)
