import math
from pathlib import Path


def polar_to_cartesian(cx: float, cy: float, radius: float, angle_rad: float):
    """Convert polar coordinates to Cartesian coordinates."""
    x = cx + radius * math.cos(angle_rad)
    y = cy + radius * math.sin(angle_rad)
    return x, y


def generate_star_points(
    cx: float,
    cy: float,
    outer_radius: float,
    inner_radius: float,
    points: int,
    rotation_deg: float = -90.0,
):
    """
    Generate a symmetric jagged star/wheel outline.

    For N points, this creates 2N vertices:
    outer, inner, outer, inner, ...

    Args:
        cx, cy: center of the shape
        outer_radius: radius of the spikes
        inner_radius: radius of the valleys
        points: number of star spikes
        rotation_deg: overall rotation of the shape
    """
    if points < 2:
        raise ValueError("points must be >= 2")
    if inner_radius <= 0 or outer_radius <= 0:
        raise ValueError("Radii must be positive")
    if inner_radius >= outer_radius:
        raise ValueError("inner_radius must be smaller than outer_radius")

    vertices = []
    start_angle = math.radians(rotation_deg)
    step = math.pi / points  # half-step because we alternate outer/inner

    for i in range(points * 2):
        radius = outer_radius if i % 2 == 0 else inner_radius
        angle = start_angle + i * step
        vertices.append(polar_to_cartesian(cx, cy, radius, angle))

    return vertices


def points_to_svg_path(points_list):
    """Convert a list of (x, y) points into an SVG path string."""
    if not points_list:
        raise ValueError("points_list cannot be empty")

    first_x, first_y = points_list[0]
    commands = [f"M {first_x:.2f} {first_y:.2f}"]
    for x, y in points_list[1:]:
        commands.append(f"L {x:.2f} {y:.2f}")
    commands.append("Z")
    return " ".join(commands)


def build_svg(
    path_d: str,
    width: int = 300,
    height: int = 300,
    fill: str = "#ffffff",
):
    """
    Create a transparent SVG containing the star path.
    """
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <title>Jagged wheel star</title>
  <path d="{path_d}" fill="{fill}"/>
</svg>
'''


def create_jagged_star_svg(
    output_file="jagged_star_50.svg",
    size=300,
    points=50,
    outer_radius=140,
    inner_radius=122,
    fill="#ffffff",
    rotation_deg=-90,
):
    """
    Generate and save a symmetric jagged wheel/star SVG.

    inner_radius controls how pointy the shape is:
    - smaller inner_radius = sharper spikes
    - larger inner_radius = softer / less pointy
    """
    cx = size / 2
    cy = size / 2

    vertices = generate_star_points(
        cx=cx,
        cy=cy,
        outer_radius=outer_radius,
        inner_radius=inner_radius,
        points=points,
        rotation_deg=rotation_deg,
    )

    path_d = points_to_svg_path(vertices)
    svg = build_svg(path_d, width=size, height=size, fill=fill)

    Path(output_file).write_text(svg, encoding="utf-8")
    return svg


if __name__ == "__main__":
    svg_code = create_jagged_star_svg(
        output_file="jagged_star_50.svg",
        size=300,
        points=30,
        outer_radius=140,
        inner_radius=122,  # closer to outer_radius = less pointy
        fill="#ffffff",
        rotation_deg=-90,
    )

    print("SVG created: jagged_star_50.svg")
    print()
    print(svg_code)