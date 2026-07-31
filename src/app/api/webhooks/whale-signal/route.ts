import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const txHash = body.transactionHash;
    
    if (!txHash) {
      return NextResponse.json({ error: 'Missing tx hash in log payload' }, { status: 400 });
    }
    
    // In full implementation, we decode the ABI CTF calldata here, 
    // fetch the wallet address + market ID, and instantly upsert into ObservedTrade
    // bypassing the 3-30 second polling latency.
    
    console.log(`[Whale Signal webhook] Received zero-latency trade! Tx: ${txHash}`);
    
    // Optionally trigger `npm run score:trades` natively in the background
    
    return NextResponse.json({ success: true, txHash });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
