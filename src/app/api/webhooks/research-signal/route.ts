import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { requireInternalAuth } from "@/lib/internal-auth";

export async function POST(req: Request) {
  const denied = requireInternalAuth(req);
  if (denied) return denied;
  try {
    const body = await req.json();

    const {
      source,
      marketCategory,
      sentimentScore,
      confidence,
      rawPayload,
    } = body;

    // Validate required fields
    if (!source || !marketCategory || typeof sentimentScore !== "number") {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    // Save the regulatory signal to Prisma
    const signal = await prisma.regulatorySignal.create({
      data: {
        source,
        marketCategory,
        sentimentScore,
        confidence: confidence || 0.5,
        rawPayload: rawPayload || "{}",
      },
    });

    console.log(`[Research Bot] Received new signal: ${marketCategory} | Sentiment: ${sentimentScore}`);

    return NextResponse.json({ success: true, signalId: signal.id }, { status: 201 });
  } catch (error: any) {
    console.error("[Research Bot Webhook Error]:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
