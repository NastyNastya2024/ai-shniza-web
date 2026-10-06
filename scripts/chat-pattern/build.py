import random, math, os, sys
from icons import I, FILL
W = H = 900
def place(seed):
    rnd = random.Random(seed)
    items = []
    def ok(x, y, r, gap):
        for (k, ix, iy, ir, *_ ) in items:
            dx = abs(x - ix); dx = min(dx, W - dx)
            dy = abs(y - iy); dy = min(dy, H - dy)
            if math.hypot(dx, dy) < r + ir + gap: return False
        return True
    keys = list(I.keys())
    order = keys + rnd.sample(keys, len(keys)) + rnd.sample(keys, len(keys))
    for k in order:
        for _ in range(3000):
            size = rnd.uniform(26, 38)
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            if ok(x, y, size * .44, 3):
                items.append((k, x, y, size * .44, size, rnd.uniform(-28, 28))); break
    fk = list(FILL.keys())
    for _ in range(50000):
        k = rnd.choice(fk)
        size = {'dot': rnd.uniform(4, 7), 'ring': rnd.uniform(8, 12), 'wave': rnd.uniform(18, 26), 'spiral': rnd.uniform(12, 18)}.get(k, rnd.uniform(10, 16))
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        if ok(x, y, size * .5, 4):
            items.append((k, x, y, size * .5, size, rnd.uniform(-30, 30)))
    return items

THEMES = {
  'dark':  ('#0F0B16', '#3A2D52', '#4A3530'),
  'light': ('#FAF7FF', '#E6E0F0', '#EDE4DC'),
}
PATTERN_OPACITY = 0.42
STROKE_W = 1.25
WARM = {'friedegg', 'mascot', 'pan', 'egg', 'chick', 'sun', 'heart', 'tinyheart', 'toast', 'bacon'}

def svg(items, theme, bg=True):
    bgc, line, warm = THEMES[theme]
    defs = ''.join(f'<symbol id="{k}" viewBox="0 0 64 64" overflow="visible">{v}</symbol>' for k, v in {**I, **FILL}.items())
    out = []
    for (k, x, y, r, size, rot) in items:
        col = warm if k in WARM else line
        for ox in (-W, 0, W):
            for oy in (-H, 0, H):
                cx, cy = x + ox, y + oy
                if cx + r < -2 or cx - r > W + 2 or cy + r < -2 or cy - r > H + 2: continue
                out.append(f'<use href="#{k}" x="{cx - size/2:.1f}" y="{cy - size/2:.1f}" width="{size:.1f}" height="{size:.1f}" transform="rotate({rot:.1f} {cx:.1f} {cy:.1f})" stroke="{col}" color="{col}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<defs><style>symbol *{{vector-effect:non-scaling-stroke}} .F{{fill:currentColor}}</style>{defs}</defs>'
            + (f'<rect width="{W}" height="{H}" fill="{bgc}"/>' if bg else '')
            + f'<g fill="none" stroke-width="{STROKE_W}" stroke-linecap="round" stroke-linejoin="round" opacity="{PATTERN_OPACITY}">{"".join(out)}</g></svg>')

if __name__ == '__main__':
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'out'
    items = place(seed)
    os.makedirs(out_dir, exist_ok=True)
    for t in THEMES:
        path = os.path.join(out_dir, f'chat-pattern-{t}.svg')
        open(path, 'w').write(svg(items, t))
        print('wrote', path, os.path.getsize(path), 'bytes')
    print(len(items), 'items')
