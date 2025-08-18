"""CLI entrypoint for RunBuddy – forwards to the orchestrator."""

import argparse
from runbuddy.app.runner import answer_free_form


def main():
    """Main entrypoint for the CLI.

    Parses the `--ask` argument from the command line,
    forwards it to `answer_free_form`, and prints a
    formatted recommendation to stdout.

    :return: None
    """
    parser = argparse.ArgumentParser(description="RunBuddy AI – free-form CLI (refactor)")
    parser.add_argument("--ask", type=str, required=True, help="Free-form question")
    args = parser.parse_args()

    ans = answer_free_form(args.ask)

    print("\n=== RunBuddy Recommendation ===")
    print(f"When:     {ans['when']['date']} {ans['when']['time']}")
    print(f"City:     {ans['city']}")
    r = ans["result"]
    print(f"Trail:    {r.get('trail_name')}")
    print(f"Reason:   {r.get('reason')}")
    if r.get("cautions"):
        print(f"Cautions: {r.get('cautions')}")


if __name__ == "__main__":
    main()

