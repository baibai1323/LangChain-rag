from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import ChatIn, FeedbackIn, PasswordChangeIn, RegisterIn, SearchTestIn, UserUpdateIn


@pytest.mark.parametrize("username", ["ab", "a" * 33, "bad name", "bad-name"])
def test_register_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValidationError):
        RegisterIn(username=username, password="123456")


def test_register_accepts_chinese_username() -> None:
    data = RegisterIn(username="张三同学", password="123456")
    assert data.username == "张三同学"


def test_register_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        RegisterIn(username="alice", password="12345")


def test_chat_rejects_empty_and_overlong_question() -> None:
    with pytest.raises(ValidationError):
        ChatIn(conversation_id="c1", question="")
    with pytest.raises(ValidationError):
        ChatIn(conversation_id="c1", question="问" * 2001)


def test_feedback_rating_must_be_minus_one_zero_or_one() -> None:
    FeedbackIn(rating=-1)
    FeedbackIn(rating=1)
    with pytest.raises(ValidationError):
        FeedbackIn(rating=2)


def test_search_top_k_bounds() -> None:
    assert SearchTestIn(query="手机", top_k=20).top_k == 20
    with pytest.raises(ValidationError):
        SearchTestIn(query="手机", top_k=0)
    with pytest.raises(ValidationError):
        SearchTestIn(query="手机", top_k=21)


def test_user_update_rejects_unknown_role_and_status() -> None:
    UserUpdateIn(role="admin", status="disabled")
    with pytest.raises(ValidationError):
        UserUpdateIn(role="superuser")
    with pytest.raises(ValidationError):
        UserUpdateIn(status="deleted")


def test_password_change_requires_new_password_length() -> None:
    with pytest.raises(ValidationError):
        PasswordChangeIn(old_password="123456", new_password="123")
