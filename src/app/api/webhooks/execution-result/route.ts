import { NextResponse } from 'next/server';
import { prisma } from '@/lib/db';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    
    await prisma.$transaction(async (tx) => {
      // 1. If compounding bot, deduct cash
      if (body.botId !== "STANDARD") {
        const bankroll = await tx.botBankroll.findUniqueOrThrow({ where: { botId: body.botId } });
        if (bankroll.cashBalance < body.simulatedPositionSize) {
          throw new Error(`Insufficient capital`);
        }
        await tx.botBankroll.update({
          where: { botId: body.botId },
          data: { cashBalance: { decrement: body.simulatedPositionSize } }
        });
      }

      // 2. Write the trade based on Rust's FAK fill confirmation
      await tx.paperTrade.create({
        data: {
          botId: body.botId,
          venue: body.venue,
          decisionJournalId: body.decisionJournalId,
          walletAddress: body.walletAddress,
          marketId: body.marketId,
          outcome: body.outcome,
          side: body.side,
          entryPrice: body.entryPrice,
          currentPrice: body.entryPrice,
          simulatedPositionSize: body.simulatedPositionSize,
        }
      });
    });
    
    console.log(`[Shadow Exec] Recorded FAK trade for ${body.botId} via Rust Engine!`);
    return NextResponse.json({ success: true });
  } catch (e: any) {
    console.error(e);
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
