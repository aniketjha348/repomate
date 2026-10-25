"""RepoMate core package.

Evidence-first open-source contribution agent:

    validate input -> pin repository snapshot -> retrieve evidence
    -> plan contribution -> generate artifact -> verify -> publish report

The package is provider-independent: AI model access goes through the
adapter in ``repomate_core.models.provider`` so the gateway can be swapped
without touching the pipeline.
"""

__version__ = "0.1.0"
