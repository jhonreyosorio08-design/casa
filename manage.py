#!/usr/bin/env python
import os
import sys
import threading
import webbrowser


def _open_development_browser():
    port = "8000"
    for argument in sys.argv[2:]:
        if argument.isdigit():
            port = argument
        elif ":" in argument and argument.rsplit(":", 1)[-1].isdigit():
            port = argument.rsplit(":", 1)[-1]
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/", new=2)
    except webbrowser.Error:
        pass


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "casa_sonata.settings")
    if len(sys.argv) > 1 and sys.argv[1] == "runserver" and os.environ.get("RUN_MAIN") != "true":
        threading.Timer(2, _open_development_browser).start()
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
