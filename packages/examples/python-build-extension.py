"""Example trusted package extension.

Package extensions are repository code executed by smart-build. They are not a
sandbox and must be reviewed with the same trust as build scripts.

smart-build hashes only the declared extension file for extension cache and
manifest metadata. Helper modules imported from this file are trusted code too,
but their contents are not included automatically; after changing a helper,
trigger a rebuild or update this declared extension file.
"""


def extend_package(context):
    name = context["name"]
    return {
        "env": {
            "SMART_BUILD_EXTENSION": "example",
        },
        "command": {
            "suffix": [f"-DSMART_BUILD_PACKAGE={name}"],
        },
    }
