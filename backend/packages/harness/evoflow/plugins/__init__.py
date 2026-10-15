"""ZCode-style plugin system for EvoFlow.

Ported from ZCode ``apps/zcode-cli/packages/adapters/src/plugins/`` so that
EvoFlow speaks the same plugin semantics: marketplace sources, ``plugin.json``
manifests, dependency closures, per-plugin enable state, and the same on-disk
storage layout (``known_marketplaces.json`` / ``installed_plugins.json`` /
``marketplaces/<id>/marketplace.json`` / ``cache/<marketplace>/<name>/<version>``).
"""
