def format_brief(reviewed, config):
    lines = []

    # Headline (if available)
    if "headline" in reviewed:
        lines.append(reviewed["headline"].upper())
        lines.append("")

    lines.append("EXECUTIVE SUMMARY")
    lines.append("")

    if "summary" in reviewed:
        lines.append(reviewed["summary"])
        lines.append("")

    lines.append("KEY POINTS")
    lines.append("")

    if "key_points" in reviewed:
        for point in reviewed["key_points"]:
            lines.append(f"- {point}")

    return "\n".join(lines)
