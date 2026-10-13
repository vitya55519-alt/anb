"""V3.60.4: every built-in girl has her own husband/boyfriend name."""
from services.custom_character_service import _PARTNER_BY_CHARACTER, relationship_line


def test_built_in_partners_are_unique():
    names = list(_PARTNER_BY_CHARACTER.values())
    assert len(names) == len(set(names))
    assert _PARTNER_BY_CHARACTER['veronika_01'] == 'Денис'


def test_line_uses_her_own_name():
    assert 'Глеб' in relationship_line('mar_married', 'alisa_01')
    assert 'Влад' in relationship_line('mar_married', 'zlata_01')
