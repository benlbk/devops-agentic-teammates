import { cookies } from 'next/headers';
import { v4 as uuidv4 } from 'uuid';
import { getCartBySession, createCart } from './db';
import type { Cart } from './types';

const CART_SESSION_COOKIE = 'cart_session_id';

export async function getOrCreateCart(userId?: string): Promise<Cart> {
  const cookieStore = cookies();
  let sessionId = cookieStore.get(CART_SESSION_COOKIE)?.value;

  if (!sessionId) {
    sessionId = uuidv4();
    cookieStore.set(CART_SESSION_COOKIE, sessionId, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 30 // 30 days
    });
  }

  let cart = await getCartBySession(sessionId);

  if (!cart) {
    cart = await createCart({
      sessionId,
      userId
    });
  } else if (userId && !cart.userId) {
    // Associate cart with user if they just logged in
    cart = await prisma.cart.update({
      where: { id: cart.id },
      data: { userId },
      include: { items: true }
    });
  }

  return cart;
}

export async function mergeAnonymousCartWithUserCart(anonymousCart: Cart, userId: string): Promise<Cart> {
  const existingUserCart = await prisma.cart.findFirst({
    where: { userId },
    include: { items: true }
  });

  if (!existingUserCart) {
    return prisma.cart.update({
      where: { id: anonymousCart.id },
      data: { userId },
      include: { items: true }
    });
  }

  // Merge items from anonymous cart into user's cart
  for (const item of anonymousCart.items) {
    const existingItem = existingUserCart.items.find(i => i.productId === item.productId);
    
    if (existingItem) {
      await prisma.cartItem.update({
        where: { id: existingItem.id },
        data: { quantity: existingItem.quantity + item.quantity }
      });
    } else {
      await prisma.cartItem.create({
        data: {
          cartId: existingUserCart.id,
          productId: item.productId,
          quantity: item.quantity,
          price: item.price,
          name: item.name
        }
      });
    }
  }

  // Delete the anonymous cart
  await prisma.cart.delete({
    where: { id: anonymousCart.id }
  });

  return prisma.cart.findUnique({
    where: { id: existingUserCart.id },
    include: { items: true }
  });
}