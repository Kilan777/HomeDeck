"""Render the board to PNG (top and bottom views) using kicad-cli svg export + cairosvg."""
import os, sys, subprocess

KICAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kicad"))
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "out"))


def render(pcb, name="board", layers_top="F.Cu,F.SilkS,Edge.Cuts,F.CrtYd,F.Paste", layers_bot="B.Cu,B.SilkS,Edge.Cuts", width=2400):
    os.makedirs(OUT, exist_ok=True)
    import cairosvg
    outs = []
    for suffix, layers, mirror in (("top", layers_top, False), ("bottom", layers_bot, True)):
        svg_dir = os.path.join(OUT, "svg_" + suffix)
        os.makedirs(svg_dir, exist_ok=True)
        cmd = ["kicad-cli", "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "2", "--exclude-drawing-sheet", "-o", os.path.join(svg_dir, "b.svg")]
        if mirror:
            cmd.append("--mirror")
        cmd.append(pcb)
        subprocess.run(cmd, check=True, capture_output=True)
        png = os.path.join(OUT, f"{name}_{suffix}.png")
        cairosvg.svg2png(url=os.path.join(svg_dir, "b.svg"), write_to=png, output_width=width, background_color="white")
        outs.append(png)
    return outs


if __name__ == "__main__":
    pcb = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KICAD_DIR, "HomeDeck.kicad_pcb")
    print(render(pcb, sys.argv[2] if len(sys.argv) > 2 else "board"))
