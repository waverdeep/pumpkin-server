import secrets

# 헷갈리는 글자(0/O, 1/l/I)를 뺀 알파벳. 카톡에서 눈으로 읽고 치는 경우가 있다.
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def new_slug(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
