"""stdin 텍스트를 텔레그램으로 전송하는 헬퍼(크론 파이프용).

Usage:  echo "본문" | python scripts/send_telegram.py --subject "제목" [--severity info]
환경변수 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 필요. 실패 시 exit 1.
"""

from __future__ import annotations

import argparse
import sys

from trade_flow.operations import Notification, TelegramNotifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument(
        "--severity", default="info", choices=["info", "warning", "error", "critical"]
    )
    args = parser.parse_args(argv)

    body = sys.stdin.read().strip()
    if not body:
        print("본문이 비어 있어 전송 생략.", file=sys.stderr)
        return 1
    notifier = TelegramNotifier.from_env()
    if notifier is None:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 미설정.", file=sys.stderr)
        return 1
    result = notifier.send(Notification(args.subject, body, args.severity))
    if not result.delivered:
        print(f"전송 실패: {result.error_code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
