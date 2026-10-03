"""Optional typo-aware normalization for embedding lookup prompts."""

from collections.abc import Callable
from importlib.resources import as_file, files

from symspellpy import SymSpell

DICTIONARY_FILENAME = "frequency_dictionary_en_82_765.txt"
PROJECT_TERMS = (
    "fastapi",
    "namespace",
    "openai",
    "pgvector",
    "semantix",
)
PROJECT_TERM_FREQUENCY = 1_000_000_000
PromptNormalizer = Callable[[str], str]


class SymSpellPromptNormalizer:
    def __init__(
        self,
        sym_spell: SymSpell,
        *,
        max_edit_distance: int,
    ) -> None:
        self._sym_spell = sym_spell
        self._max_edit_distance = max_edit_distance

    @classmethod
    def load(cls, *, max_edit_distance: int) -> "SymSpellPromptNormalizer":
        sym_spell = SymSpell(
            max_dictionary_edit_distance=max_edit_distance,
        )

        try:
            dictionary_resource = files("symspellpy").joinpath(DICTIONARY_FILENAME)
            with as_file(dictionary_resource) as dictionary_path:
                loaded = sym_spell.load_dictionary(
                    dictionary_path,
                    term_index=0,
                    count_index=1,
                )
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "Prompt typo correction is enabled, but the bundled "
                "SymSpell English frequency dictionary could not be loaded"
            ) from exc

        if not loaded:
            raise RuntimeError(
                "Prompt typo correction is enabled, but the bundled "
                "SymSpell English frequency dictionary could not be loaded"
            )

        for term in PROJECT_TERMS:
            sym_spell.create_dictionary_entry(
                term,
                PROJECT_TERM_FREQUENCY,
            )

        return cls(
            sym_spell,
            max_edit_distance=max_edit_distance,
        )

    def normalize(self, prompt: str) -> str:
        suggestions = self._sym_spell.lookup_compound(
            prompt,
            max_edit_distance=self._max_edit_distance,
            ignore_non_words=True,
            transfer_casing=True,
            ignore_term_with_digits=True,
        )
        if not suggestions:
            return prompt

        normalized = suggestions[0].term.strip()
        return normalized or prompt


def preserve_prompt(prompt: str) -> str:
    return prompt


def create_prompt_normalizer(
    *,
    enabled: bool,
    max_edit_distance: int,
) -> PromptNormalizer:
    if not enabled:
        return preserve_prompt

    return SymSpellPromptNormalizer.load(
        max_edit_distance=max_edit_distance,
    ).normalize
