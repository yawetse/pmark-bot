"""Target-wallets repository — top-N wallets passing daily-refresh thresholds.

Traces: REQ-DATA-007.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import Money, Probability, TargetWallet
from claude_poly_bot.storage.orm import TargetWallets


class SqlAlchemyTargetWalletRepo:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def upsert_all(self, wallets: list[TargetWallet]) -> None:
        """Replace the entire target-wallet set in one transaction.

        Daily refresh writes the new top-N; old rows are removed.
        """
        async with self._sm() as session, session.begin():
            await session.execute(delete(TargetWallets))
            for w in wallets:
                session.add(
                    TargetWallets(
                        address=w.address,
                        total_trades=w.total_trades,
                        win_rate=w.win_rate,
                        total_pnl=w.total_pnl,
                        refreshed_at=w.refreshed_at,
                    )
                )

    async def list_current(self) -> list[TargetWallet]:
        async with self._sm() as session:
            rows = (await session.execute(select(TargetWallets))).scalars().all()
        return [
            TargetWallet(
                address=r.address,
                total_trades=r.total_trades,
                win_rate=Probability(r.win_rate),
                total_pnl=Money(r.total_pnl),
                refreshed_at=r.refreshed_at,
            )
            for r in rows
        ]
