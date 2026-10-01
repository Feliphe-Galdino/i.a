import json

import pytest

from sexta.memory.conversations import ConversationService
from sexta.memory.db import MIGRATIONS, Database
from sexta.memory.memories import MemoryService


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    yield database
    database.close()


@pytest.fixture
def memory(db):
    return MemoryService(db)


def test_migrations_apply_once(tmp_path):
    path = tmp_path / "m.db"
    first = Database(path)
    assert first.schema_version == len(MIGRATIONS)
    first.close()
    second = Database(path)  # reabrir não reaplica
    assert second.schema_version == len(MIGRATIONS)
    second.close()


def test_add_search_and_accent_insensitive(memory):
    memory.add("O usuário estuda programação em Python", category="perfil", tags=["python"])
    memory.add("Prefere respostas curtas e diretas", category="preferencias")
    results = memory.search("programacao")
    assert results and "Python" in results[0].content
    assert memory.search("respostas")[0].category == "preferencias"


def test_duplicates_are_merged(memory):
    first, created = memory.add("Mora em São Paulo", importance=2)
    second, created_again = memory.add("mora em sao paulo!", importance=4, tags=["cidade"])
    assert created and not created_again
    assert first.id == second.id
    assert second.importance == 4
    assert "cidade" in second.tags


def test_update_and_delete(memory):
    item, _ = memory.add("Projeto Sexta-Feira usa FastAPI", category="projetos")
    updated = memory.update(item.id, content="Projeto Sexta-Feira usa FastAPI e SQLite", importance=5, pinned=True)
    assert updated.pinned and updated.importance == 5
    assert memory.search("SQLite")[0].id == item.id  # índice FTS atualizado
    assert memory.delete(item.id)
    assert memory.get(item.id) is None
    assert memory.search("SQLite") == []


def test_relevant_for_includes_pinned(memory):
    memory.add("O nome do usuário é Feliphe", category="perfil", pinned=True, importance=5)
    memory.add("Gosta de café sem açúcar", category="preferencias")
    memory.add("Usa Windows 11 no notebook", category="perfil")
    relevant = memory.relevant_for("qual sistema operacional eu uso no notebook?")
    contents = [m.content for m in relevant]
    assert "O nome do usuário é Feliphe" in contents
    assert "Usa Windows 11 no notebook" in contents
    assert "Gosta de café sem açúcar" not in contents


def test_search_with_special_characters_is_safe(memory):
    memory.add("Teste de busca")
    assert memory.search('"; DROP TABLE memories; -- AND OR NEAR(') == []
    assert memory.search("") == []


def test_export_import_roundtrip(memory, tmp_path):
    memory.add("Fato A", category="conhecimento", tags=["a"])
    memory.add("Fato B", category="projetos", pinned=True)
    exported = memory.export()
    assert exported["format"] == "sexta-feira.memories"
    other = MemoryService(Database(tmp_path / "other.db"))
    result = other.import_(json.dumps(exported))
    assert result == {"created": 2, "updated": 0, "skipped": 0}
    assert other.import_(exported)["updated"] == 2  # reimportar não duplica
    assert {m.content for m in other.list()} == {"Fato A", "Fato B"}


def test_import_rejects_invalid(memory):
    with pytest.raises(ValueError):
        memory.import_({"nada": []})


def test_conversation_history_roundtrip(db):
    convs = ConversationService(db)
    conv = convs.create(
        system_prompt="sys", title="Uma conversa sobre arquitetura de software muito longa demais para o título"
    )
    assert len(conv["title"]) <= 60
    convs.append(
        conv["id"],
        role="user",
        kind="user",
        content=[{"type": "text", "text": "ctx"}, {"type": "text", "text": "olá"}],
        display_text="olá",
    )
    convs.append(
        conv["id"],
        role="assistant",
        kind="assistant",
        content=[
            {"type": "thinking", "thinking": "pensando", "signature": "sig"},
            {"type": "text", "text": "Vou salvar."},
            {"type": "tool_use", "id": "t1", "name": "memory_save", "input": {"content": "x"}},
        ],
        display_text="Vou salvar.",
    )
    convs.append(
        conv["id"],
        role="user",
        kind="tool_results",
        content=[{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
    )
    api = convs.api_messages(conv["id"])
    assert [m["role"] for m in api] == ["user", "assistant", "user"]
    assert api[1]["content"][0]["signature"] == "sig"  # preservado byte a byte
    view = convs.view(conv["id"])
    assert view[1]["tools"][0]["result"] == "ok"
    assert view[1]["thinking"] == "pensando"
    assert convs.search_messages("salvar")[0]["conversation_id"] == conv["id"]
    assert convs.delete(conv["id"])
    assert convs.api_messages(conv["id"]) == []
