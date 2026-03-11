import re
from html import escape
from pathlib import Path
from typing import Optional


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:<)?([^)>]+)(?:>)?\)")


def _safe(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = slug.replace("&", "and")
    slug = re.sub(r"[']", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _normalize_url(url: str) -> str:
    if not url:
        return "#"
    if url.startswith(("http://", "https://", "/", "#")):
        return url
    return f"/{url}"


def _build_link_lookup(env) -> dict[str, list[str]]:
    """
    Build an automatic lookup from MkDocs navigation.
    Supports matching by title, filename stem, article-stripped title,
    and normalized punctuation variants.
    """
    lookup: dict[str, list[str]] = {}

    nav = env.variables.get("navigation")
    pages = getattr(nav, "pages", []) or []

    for page in pages:
        title = getattr(page, "title", None)
        url = getattr(page, "url", None)
        src_path = getattr(page, "src_path", None)

        if not url:
            continue

        normalized_url = _normalize_url(url)
        all_keys: set[str] = set()

        if title:
            all_keys.update(_generate_lookup_keys(title))

        if src_path:
            stem = Path(src_path).stem
            all_keys.update(_generate_lookup_keys(stem))

        for key in all_keys:
            if key not in lookup:
                lookup[key] = []
            if normalized_url not in lookup[key]:
                lookup[key].append(normalized_url)

    return lookup

def _generate_lookup_keys(value: str) -> set[str]:
    """
    Automatically generate lookup keys from a title or filename.
    No manual aliases required.
    """
    value = _safe(value)
    if not value:
        return set()

    keys: set[str] = set()

    raw = value.strip()
    lower = raw.lower()
    slug = _slugify(raw)

    keys.add(raw)
    keys.add(lower)
    keys.add(slug)

    # Normalize common punctuation/spacing variants
    simplified = re.sub(r"[-_]+", " ", lower)
    simplified = re.sub(r"[']", "", simplified)
    simplified = re.sub(r"\s+", " ", simplified).strip()

    if simplified:
        keys.add(simplified)
        keys.add(_slugify(simplified))

    # Auto-strip leading article for title-style names like "The Surface"
    no_article = re.sub(r"^(the|a|an)\s+", "", simplified, flags=re.IGNORECASE).strip()
    if no_article:
        keys.add(no_article)
        keys.add(_slugify(no_article))

    return {k for k in keys if k}

def _resolve_target(target: str, env, allow_fallback: bool = True) -> tuple[Optional[str], bool, bool]:
    """
    Returns:
    - url or None
    - exists
    - ambiguous
    """
    lookup = _build_link_lookup(env)
    target_safe = _safe(target)

    candidate_keys = list(_generate_lookup_keys(target_safe))

    matches: list[str] = []
    for key in candidate_keys:
        for url in lookup.get(key, []):
            if url not in matches:
                matches.append(url)

    if len(matches) == 1:
        return matches[0], True, False

    if len(matches) > 1:
        return None, False, True

    if allow_fallback:
        return f"/{_slugify(target_safe)}/", False, False

    return None, False, False


def _resolve_target_to_url(target: str, env) -> str:
    url, exists, ambiguous = _resolve_target(target, env, allow_fallback=True)
    return url or "#"


def _replace_wikilinks(text: str, env) -> str:
    def repl(match: re.Match) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()

        href, exists, ambiguous = _resolve_target(target, env, allow_fallback=True)

        classes = ["jr-wikilink"]
        attrs = []

        if ambiguous:
            classes.append("jr-wikilink--ambiguous")
            attrs.append(f'title="{escape(target)} matches multiple pages"')
            href = "#"
        elif not exists:
            classes.append("jr-wikilink--missing")
            attrs.append(f'title="Missing page: {escape(target)}"')

        class_attr = " ".join(classes)
        extra_attrs = f" {' '.join(attrs)}" if attrs else ""

        return f'<a href="{escape(href or "#")}" class="{class_attr}"{extra_attrs}>{escape(label)}</a>'

    return WIKILINK_RE.sub(repl, text)


def _replace_markdown_links(text: str, env) -> str:
    current_page = env.variables.get("page")
    current_url = getattr(current_page, "url", "") or ""
    current_url = current_url.strip("/")

    if "/" in current_url:
        current_dir = "/" + current_url.rsplit("/", 1)[0]
    elif current_url:
        current_dir = "/" + current_url
    else:
        current_dir = ""

    def repl(match: re.Match) -> str:
        label = match.group(1).strip()
        href = match.group(2).strip()

        if href.startswith("./"):
            href = f"{current_dir}/{href[2:]}"
        elif href.endswith(".md"):
            href = "/" + href.replace(".md", "/").lstrip("/")

        href = href.replace(".md", "/")
        href = _normalize_url(href)

        return f'<a href="{escape(href)}">{escape(label)}</a>'

    return MARKDOWN_LINK_RE.sub(repl, text)


def _format_value(value: Optional[str], env) -> str:
    value = _safe(value)
    if not value:
        return ""

    value = _replace_markdown_links(value, env)
    value = _replace_wikilinks(value, env)

    return value


def _render_value(value, env) -> str:
    """
    Allows values to be:
    - strings
    - multiline strings
    - lists (rendered as bullet lists)
    """
    if value is None:
        return ""

    if isinstance(value, list):
        items = []
        for v in value:
            v = _format_value(v, env)
            if v:
                items.append(f"<li>{v}</li>")
        if items:
            return f"<ul>{''.join(items)}</ul>"
        return ""

    value = _safe(value)
    if not value:
        return ""

    value = _format_value(value, env)
    value = value.replace("\n", "<br>")

    return value


def _row(label: str, value, env) -> str:
    formatted = _render_value(value, env)

    if not formatted:
        return ""

    return f"""
    <div class="jr-infobox__row">
      <span class="jr-infobox__label">{escape(label)}</span>
      <span class="jr-infobox__value">{formatted}</span>
    </div>
    """


def _section(title: str, rows: list[tuple[str, Optional[str]]], env) -> str:
    valid_rows = [_row(label, value, env) for label, value in rows if _safe(value)]
    valid_rows = [row for row in valid_rows if row.strip()]
    if not valid_rows:
        return ""

    return f"""
    <div class="jr-infobox__section">{escape(title)}</div>
    {''.join(valid_rows)}
    """


def _build_infobox(
    env,
    title: str,
    variant: str = "default",
    image: Optional[str] = None,
    image_alt: Optional[str] = None,
    sections: Optional[list[tuple[str, list[tuple[str, Optional[str]]]]]] = None,
) -> str:
    title = _safe(title)
    variant = _safe(variant) or "default"
    image = _safe(image)
    image_alt = _safe(image_alt) or title

    html: list[str] = [f'<div class="jr-infobox jr-infobox--{escape(variant)}">']
    html.append(f'<div class="jr-infobox__title">{escape(title)}</div>')

    if image:
        html.append(
            f"""
            <div class="jr-infobox__image">
              <img src="{escape(image)}" alt="{escape(image_alt)}">
            </div>
            """
        )

    for section_title, rows in sections or []:
        block = _section(section_title, rows, env)
        if block.strip():
            html.append(block)

    html.append("</div>")
    return "\n".join(html)


def _get_current_page_source(env) -> tuple[str, str]:
    """
    Returns:
    - current page source markdown
    - current page stem
    """
    page = env.variables.get("page")
    if not page:
        return "", ""

    file_obj = getattr(page, "file", None)
    src_path = getattr(file_obj, "src_path", None)

    if not src_path:
        return "", ""

    docs_dir = env.conf.get("docs_dir", "docs")
    full_path = Path(docs_dir) / src_path
    stem = Path(src_path).stem

    if not full_path.exists():
        return "", stem

    try:
        return full_path.read_text(encoding="utf-8"), stem
    except Exception:
        return "", stem


def _extract_wikilinks(text: str) -> list[tuple[str, str]]:
    """
    Returns list of:
    - target
    - label
    """
    links: list[tuple[str, str]] = []

    for match in WIKILINK_RE.finditer(text):
        target = _safe(match.group(1))
        label = _safe(match.group(2)) or target
        if target:
            links.append((target, label))

    return links


def _dedupe_links(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []

    for target, label in links:
        key = target.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append((target, label))

    return result


def _render_see_also(env, heading: str = "See Also", exclude: Optional[list[str]] = None) -> str:
    source, current_stem = _get_current_page_source(env)
    if not source:
        return ""

    exclude_set = {current_stem.strip().lower(), _slugify(current_stem)}

    page = env.variables.get("page")
    page_title = _safe(getattr(page, "title", None))
    if page_title:
        exclude_set.add(page_title.lower())
        exclude_set.add(_slugify(page_title))

    for item in exclude or []:
        item = _safe(item)
        if item:
            exclude_set.add(item.lower())
            exclude_set.add(_slugify(item))

    raw_links = _dedupe_links(_extract_wikilinks(source))

    items: list[str] = []

    for target, label in raw_links:
        target_key = target.strip().lower()
        target_slug = _slugify(target)

        if target_key in exclude_set or target_slug in exclude_set:
            continue

        href, exists, ambiguous = _resolve_target(target, env, allow_fallback=False)

        if not exists or ambiguous or not href:
            continue

        items.append(f'- <a href="{escape(href)}">{escape(label)}</a>')

    if not items:
        return ""

    return f"\n---\n\n## {escape(heading)}\n\n" + "\n".join(items)


def define_env(env):
    @env.macro
    def see_also(heading="See Also", exclude=None):
        return _render_see_also(env, heading=heading, exclude=exclude)

    @env.macro
    def infobox(title, image=None, image_alt=None, sections=None, variant="default"):
        return _build_infobox(
            env=env,
            title=title,
            variant=variant,
            image=image,
            image_alt=image_alt,
            sections=sections,
        )

    @env.macro
    def location_box(
        title,
        type=None,
        status=None,
        region=None,
        position=None,
        image=None,
        image_alt=None,
        affiliation=None,
        population=None,
        leader=None,
    ):
        return _build_infobox(
            env=env,
            title=title,
            variant="location",
            image=image,
            image_alt=image_alt,
            sections=[
                (
                    "Classification",
                    [
                        ("Type", type),
                        ("Status", status),
                    ],
                ),
                (
                    "Location",
                    [
                        ("Region", region),
                        ("Position", position),
                    ],
                ),
                (
                    "Additional Information",
                    [
                        ("Leader", leader),
                        ("Affiliation", affiliation),
                        ("Population", population),
                    ],
                ),
            ],
        )

    @env.macro
    def character_box(
        title,
        role=None,
        occupation=None,
        affiliation=None,
        age=None,
        gender=None,
        firstApperance=None,
        voiceActor=None,
        status=None,
        image=None,
        image_alt=None,
    ):
        return _build_infobox(
            env=env,
            title=title,
            variant="character",
            image=image,
            image_alt=image_alt,
            sections=[
                (
                    "Profile",
                    [
                        ("Role", role),
                        ("Occupation", occupation),
                        ("Affiliation", affiliation),
                    ],
                ),
                (
                    "Personal",
                    [
                        ("Age", age),
                        ("Gender", gender),
                        ("Status", status),
                    ],
                ),
                (
                    "Additional Information",
                    [
                        ("First Apperance", firstApperance),
                        ("Voice Actor", voiceActor),
                    ],
                ),
            ],
        )

    @env.macro
    def creature_box(
        title,
        type=None,
        origin=None,
        habitat=None,
        behavior=None,
        status=None,
        image=None,
        image_alt=None,
    ):
        return _build_infobox(
            env=env,
            title=title,
            variant="creature",
            image=image,
            image_alt=image_alt,
            sections=[
                (
                    "Classification",
                    [
                        ("Type", type),
                        ("Origin", origin),
                        ("Status", status),
                    ],
                ),
                (
                    "Characteristics",
                    [
                        ("Habitat", habitat),
                        ("Behavior", behavior),
                    ],
                ),
            ],
        )

    @env.macro
    def faction_box(
        title,
        type=None,
        status=None,
        base=None,
        role=None,
        image=None,
        image_alt=None,
    ):
        return _build_infobox(
            env=env,
            title=title,
            variant="faction",
            image=image,
            image_alt=image_alt,
            sections=[
                (
                    "Classification",
                    [
                        ("Type", type),
                        ("Status", status),
                    ],
                ),
                (
                    "Details",
                    [
                        ("Base", base),
                        ("Role", role),
                    ],
                ),
            ],
        )

    @env.macro
    def weapon_box(
        title,
        type=None,
        ammunition=None,
        usage=None,
        status=None,
        image=None,
        image_alt=None,
    ):
        return _build_infobox(
            env=env,
            title=title,
            variant="weapon",
            image=image,
            image_alt=image_alt,
            sections=[
                (
                    "Classification",
                    [
                        ("Type", type),
                        ("Ammunition", ammunition),
                        ("Status", status),
                    ],
                ),
                (
                    "Details",
                    [
                        ("Usage", usage),
                    ],
                ),
            ],
        )