"""Run the repository-only provider verifier through its stable CLI entrypoint."""

from provider_live_verification.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
