#!/usr/bin/env python3
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ANDROID_VALUE = f"{{{ANDROID_NS}}}value"
ANDROID_AUTHORITIES = f"{{{ANDROID_NS}}}authorities"
ANDROID_EXPORTED = f"{{{ANDROID_NS}}}exported"
ANDROID_INIT_ORDER = f"{{{ANDROID_NS}}}initOrder"


def load_string_resources(res_dir: str) -> dict[str, str]:
    values_dir = Path(res_dir)
    result: dict[str, str] = {}
    if not values_dir.exists():
        return result

    for values_path in values_dir.glob("values*/strings.xml"):
        try:
            tree = ET.parse(values_path)
            root = tree.getroot()
        except Exception:
            continue

        for node in root.findall("string"):
            name = node.attrib.get("name")
            if not name:
                continue
            text = "".join(node.itertext()) if node.text is not None else ""
            if text:
                result[name] = text

    return result


def inline_manifest_meta_data_string_values(application: ET.Element, string_table: dict[str, str]):
    if not string_table:
        return

    for element in application.iter():
        value = element.attrib.get(ANDROID_VALUE)
        if not value:
            continue

        if value.startswith("@string/"):
            name = value.split("/", 1)[1]
            resolved = string_table.get(name)
            if resolved:
                element.set(ANDROID_VALUE, resolved)


def ensure_bootstrap_provider(application: ET.Element, provider_class: str):
    for provider in application.findall("provider"):
        if provider.attrib.get(ANDROID_NAME) == provider_class:
            return

    provider = ET.SubElement(application, "provider")
    provider.set(ANDROID_NAME, provider_class)
    provider.set(ANDROID_AUTHORITIES, "${applicationId}.kapp-bootstrap")
    provider.set(ANDROID_EXPORTED, "false")
    provider.set(ANDROID_INIT_ORDER, "1000")


def patch_manifest(manifest_path: str, provider_class: str, meta_key: str, res_dir: str | None = None):
    ET.register_namespace("android", ANDROID_NS)
    tree = ET.parse(manifest_path)
    root = tree.getroot()

    print(f"DEBUG: Patching manifest at {manifest_path}")
    application = root.find("application")
    if application is None:
        print("DEBUG: <application> not found!")
        raise RuntimeError("No <application> element found in AndroidManifest.xml")

    original_app = application.attrib.get(ANDROID_NAME, "")
    print(f"DEBUG: Original application: '{original_app}'")

    meta_node = None
    for child in application.findall("meta-data"):
        if child.attrib.get(ANDROID_NAME) == meta_key:
            meta_node = child
            break

    if meta_node is None:
        meta_node = ET.SubElement(application, "meta-data")

    meta_node.set(ANDROID_NAME, meta_key)
    meta_node.set(ANDROID_VALUE, original_app)

    ensure_bootstrap_provider(application, provider_class)

    if res_dir:
        print(f"DEBUG: Loading string resources from {res_dir}")
        strings = load_string_resources(res_dir)
        print(f"DEBUG: Found {len(strings)} strings")
        inline_manifest_meta_data_string_values(application, strings)

    print("DEBUG: Writing patched manifest...")
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)
    return original_app


def main():
    parser = argparse.ArgumentParser(description="Patch decoded AndroidManifest.xml for shell bootstrap")
    parser.add_argument("--manifest", required=True, help="Path to decoded AndroidManifest.xml")
    parser.add_argument("--provider", default="com.kapp.shell.BootstrapProvider", help="Bootstrap ContentProvider class name")
    parser.add_argument("--meta-key", default="kapp.original_application", help="Meta-data key to store original app class")
    parser.add_argument("--res-dir", default=None, help="Decoded res directory for resolving @string references")
    args = parser.parse_args()

    original = patch_manifest(args.manifest, args.provider, args.meta_key, args.res_dir)
    print(f"Patched manifest. Original application: '{original}'")


if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR in manifest_patch: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
