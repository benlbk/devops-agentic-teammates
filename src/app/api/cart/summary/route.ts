import { NextResponse } from 'next/server';
import { cartService } from '@/lib/cart/cartService';

export async function GET() {
  try {
    const summary = cartService.getCartSummary();
    return NextResponse.json(summary);
  } catch (error) {
    console.error('Error getting cart summary:', error);
    return NextResponse.json(
      { error: 'Failed to get cart summary' },
      { status: 500 }
    );
  }
}
