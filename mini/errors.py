"""Error types that carry a source position for friendly diagnostics."""


class MiniError(Exception):
    kind = "Error"

    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.trace = []  # call frames, innermost first

    def __str__(self):
        where = f" at {self.line}:{self.col}" if self.line is not None else ""
        return f"{self.kind}{where}: {self.message}"

    def render(self, source: str) -> str:
        """Format the error with the offending source line and a caret."""
        text = str(self)
        if self.line is None:
            return text + "".join(f"\n  {f}" for f in self.trace)
        lines = source.splitlines()
        if not 1 <= self.line <= len(lines):
            return text
        src_line = lines[self.line - 1]
        gutter = f"{self.line:>4} | "
        caret = " " * (len(gutter) + self.col - 1) + "^"
        frames = "".join(f"\n  {f}" for f in self.trace)
        return f"{text}\n{gutter}{src_line}\n{caret}{frames}"


class MiniSyntaxError(MiniError):
    kind = "SyntaxError"


class MiniRuntimeError(MiniError):
    kind = "RuntimeError"
