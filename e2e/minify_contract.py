#!/usr/bin/env python3
"""Minify a GenLayer intelligent contract for deploy, preserving semantics exactly.

WHY: Bradbury enforces a server-side per-tx pubdata cap (BlockPubdataLimitReached;
largest known-good deploy ~39,869 B). The canonical proofmark.py (~71.7 KB) far
exceeds it. This removes ONLY bytes that can never affect runtime -- real COMMENT
tokens, standalone string-literal expression statements (docstrings), blank lines
and trailing whitespace -- never any byte inside a code STRING value (multiline
prompts etc.), and it produces a semantically identical build that fits.

SAFETY MODEL (each rule is individually load-bearing):
- The `# { "Depends": "..." }` first line is a dependency-pinning header for the
  genlayer deploy toolchain and is PRESERVED verbatim (all other comments are
  dropped).
- Docstring removal is a precise byte-span splice of `ast.Expr(ast.Constant(str))`
  statements (a bare string expression evaluates to a constant and is discarded by
  the VM). A docstring that is the ONLY statement of a suite is KEPT, because
  deleting it would leave an empty body and break parsing.
- Multi-line string *values* (assigned prompts, returns, etc.) are ordinary STRING
  tokens that are never in a docstring span, so every byte of their content is
  preserved.
- VERIFICATION GATES built into the script:
    1. final text parses with ast;
    2. token-equivalence: the stream of code tokens (everything except comments,
       whitespace, and docstring STRING tokens) is IDENTICAL between source and
       build. Any accidental code change trips this;
    3. `code_only` is a fixed point on the build (nothing left to strip).
  Combined with `genvm-lint check` and the full direct-test suite run against the
  build, this proves no logic changed.

USAGE:  python e2e/minify_contract.py <src.py> <out.py>
"""
import ast
import hashlib
import io
import sys
import tokenize
from pathlib import Path


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def line_offsets(text: str) -> list[int]:
    """Absolute char offset of the start of each 1-based line (newline counts)."""
    offs = [0]
    for line in text.split("\n"):
        offs.append(offs[-1] + len(line) + 1)  # +1 for the '\n' separator
    return offs  # offs[i] = start of line i+1; last entry past EOF


def docstring_ranges(text: str) -> tuple[list[tuple[int, int]], int]:
    """Absolute [start,end) byte spans of Expr(Constant(str)) statements.

    A standalone string that is the ONLY statement of some enclosing suite is
    KEPT: deleting it would leave that suite empty and break parsing (e.g. a
    function whose body is just its docstring). Every other Expr(Constant(str))
    is removed -- a bare string expression is discarded by the VM.
    """
    tree = ast.parse(text)
    offs = line_offsets(text)
    ranges: list[tuple[int, int]] = []

    # parent map so we can see which suite a docstring lives in.
    parent: dict[int, ast.AST] = {}
    for pnode in ast.walk(tree):
        for _field, child in ast.iter_fields(pnode):
            if isinstance(child, list):
                for item in child:
                    if isinstance(item, ast.AST):
                        parent[id(item)] = pnode
            elif isinstance(child, ast.AST):
                parent[id(child)] = pnode

    def keeps_suite_alive(doc) -> bool:
        """True if `doc` is the only statement of any enclosing suite."""
        par = parent.get(id(doc))
        while par is not None:
            for _field, child in ast.iter_fields(par):
                if isinstance(child, list) and child and child[0] is doc \
                        and len(child) == 1:
                    return True  # removing it would empty this suite
            par = parent.get(id(par))
        return False

    kept = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            if keeps_suite_alive(node):
                kept += 1
                continue
            a = offs[node.lineno - 1] + node.col_offset
            b = offs[node.end_lineno - 1] + node.end_col_offset
            ranges.append((a, b))
    return ranges, kept


def build(text: str) -> str:
    # ---- tokenize once: find every real comment token --------------------
    comments: list[tuple[int, int]] = []   # absolute spans
    string_tokens: list[tuple[int, int, str]] = []  # (start,end,raw) for checks
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError as exc:  # pragma: no cover
        raise SystemExit(f"tokenize failed: {exc}")
    offs = line_offsets(text)
    for tok in toks:
        ttype, tstr, (sr, sc), (er, ec) = tok.type, tok.string, tok.start, tok.end
        a, b = offs[sr - 1] + sc, offs[er - 1] + ec
        if ttype == tokenize.COMMENT:
            # Preserve the line-1 dependency-pinning header verbatim.
            stripped = text.split("\n")[sr - 1].strip()
            if sr == 1 and stripped.startswith("# {"):
                continue
            comments.append((a, b))
        elif ttype == tokenize.STRING:
            string_tokens.append((a, b, tstr))

    # ---- docstring spans + the ones that must stay ------------------------
    doc_ranges, kept_docstrings = docstring_ranges(text)

    # ---- assemble removal intervals ---------------------------------------
    removed = sorted(comments + doc_ranges)  # no overlaps possible

    # Splice from the end so earlier offsets stay valid.
    buf = text
    for a, b in reversed(removed):
        buf = buf[:a] + buf[b:]

    # ---- normalize: drop blank lines, trim trailing whitespace ------------
    out = "\n".join(ln.rstrip() for ln in buf.split("\n") if ln.strip())
    out = out.rstrip() + "\n"

    # ---- GATE 1: parses -----------------------------------------------------
    try:
        ast.parse(out)
    except SyntaxError as exc:
        raise SystemExit(f"GATE FAIL ast.parse: {exc}")

    # ---- GATE 2: code-token equivalence --------------------------------------
    def code_tokens(src: str, skip_doc_ranges: list[tuple[int, int]]):
        offs2 = line_offsets(src)
        keep_ranges = sorted(skip_doc_ranges)
        seq = []

        def in_doc(a: int) -> bool:
            lo, hi = 0, len(keep_ranges)
            while lo < hi:
                mid = (lo + hi) // 2
                s, e = keep_ranges[mid]
                if a < s:
                    hi = mid
                elif a >= e:
                    lo = mid + 1
                else:
                    return True
            return False

        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            ttype, tstr, (sr, sc), (er, ec) = tok.type, tok.string, tok.start, tok.end
            a = offs2[sr - 1] + sc
            if ttype in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                         tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
                         tokenize.ENDMARKER):
                continue
            if ttype == tokenize.STRING and in_doc(a):
                continue  # this STRING token was part of a removed docstring
            seq.append((ttype, tstr))
        return seq

    src_toks = code_tokens(text, doc_ranges)
    out_toks = code_tokens(out, [])
    if src_toks != out_toks:
        # Find the first divergence for a helpful message.
        for i, (s, o) in enumerate(zip(src_toks, out_toks)):
            if s != o:
                raise SystemExit(
                    f"GATE FAIL token drift at #{i}: src={s} build={o}")
        raise SystemExit(
            f"GATE FAIL token count {len(src_toks)} != {len(out_toks)}")

    # ---- GATE 3: fixed point -----------------------------------------------
    # Re-stripping the build (docstring pass will now find nothing) must be a
    # no-op apart from nothing to remove. Cheap sanity: no docstring ranges left.
    if docstring_ranges(out)[0]:
        raise SystemExit("GATE FAIL: build still contains docstring expressions")

    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")
    projected = build(text)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" so line endings are LF on every platform -- CRLF would pad the
    # file and shrink the margin against the deploy pubdata cap for no benefit.
    with dst.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(projected)
    print(f"src : {src}  {len(text.encode())} B  sha256 {sha(text)[:16]}")
    print(f"dst : {dst}  {len(projected.encode())} B  sha256 {sha(projected)[:16]}")
    print(f"removed {len(text.encode()) - len(projected.encode())} B "
          f"({100 * (1 - len(projected.encode()) / len(text.encode())):.1f}%)")
    print("gates: ast.parse OK, code-token equivalence OK, fixed-point OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
