from PyInstaller.utils.hooks import collect_submodules

# Rich uses Pygments for Python tracebacks and shell snippets in help.
hiddenimports = ["pygments.lexers.python", "pygments.lexers.shell", "pygments.lexers.special"]
hiddenimports += collect_submodules("pygments.formatters") + collect_submodules("pygments.styles")
