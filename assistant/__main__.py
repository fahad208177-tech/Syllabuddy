from syllabus_core.envfile import load_env

load_env()

from assistant.app import main  # noqa: E402  (env must be loaded before the brain is chosen)

main()
