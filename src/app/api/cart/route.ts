import { NextResponse } from 'next/server';
import { getOrCreateCart } from '@/lib/cart/session';
import { addCartItem, updateCartItem, removeCartItem } from '@/lib/cart/db';
import { auth } from '@/lib/auth';

export async function GET() {
  try {
    const session = await auth();
    const cart = await getOrCreateCart(session?.user?.id);
    return NextResponse.json(cart);
  } catch (error) {
    console.error('Failed to get cart:', error);
    return NextResponse.json({ error: 'Failed to get cart' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const session = await auth();
    const cart = await getOrCreateCart(session?.user?.id);
    const data = await request.json();

    const updatedCart = await addCartItem({
      cartId: cart.id,
      ...data
    });

    return NextResponse.json(updatedCart);
  } catch (error) {
    console.error('Failed to add item to cart:', error);
    return NextResponse.json({ error: 'Failed to add item to cart' }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  try {
    const data = await request.json();
    const updatedCart = await updateCartItem(data);
    return NextResponse.json(updatedCart);
  } catch (error) {
    console.error('Failed to update cart item:', error);
    return NextResponse.json({ error: 'Failed to update cart item' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const { cartId, itemId } = await request.json();
    const updatedCart = await removeCartItem(cartId, itemId);
    return NextResponse.json(updatedCart);
  } catch (error) {
    console.error('Failed to remove cart item:', error);
    return NextResponse.json({ error: 'Failed to remove cart item' }, { status: 500 });
  }
}