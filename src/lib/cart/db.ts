import { prisma } from '@/lib/prisma';
import { Cart, CreateCartInput, AddCartItemInput, UpdateCartItemInput } from './types';

export async function createCart(input: CreateCartInput): Promise<Cart> {
  return prisma.cart.create({
    data: {
      userId: input.userId,
      sessionId: input.sessionId,
      items: [],
      total: 0
    },
    include: {
      items: true
    }
  });
}

export async function getCart(cartId: string): Promise<Cart | null> {
  return prisma.cart.findUnique({
    where: { id: cartId },
    include: {
      items: true
    }
  });
}

export async function getCartBySession(sessionId: string): Promise<Cart | null> {
  return prisma.cart.findFirst({
    where: { sessionId },
    include: {
      items: true
    }
  });
}

export async function addCartItem(input: AddCartItemInput): Promise<Cart> {
  const cart = await prisma.cart.update({
    where: { id: input.cartId },
    data: {
      items: {
        create: {
          productId: input.productId,
          quantity: input.quantity,
          price: input.price,
          name: input.name
        }
      },
      total: {
        increment: input.price * input.quantity
      }
    },
    include: {
      items: true
    }
  });

  return cart;
}

export async function updateCartItem(input: UpdateCartItemInput): Promise<Cart> {
  const item = await prisma.cartItem.findUnique({
    where: { id: input.itemId }
  });

  if (!item) {
    throw new Error('Cart item not found');
  }

  const priceDiff = (input.quantity - item.quantity) * item.price;

  return prisma.cart.update({
    where: { id: input.cartId },
    data: {
      items: {
        update: {
          where: { id: input.itemId },
          data: { quantity: input.quantity }
        }
      },
      total: {
        increment: priceDiff
      }
    },
    include: {
      items: true
    }
  });
}

export async function removeCartItem(cartId: string, itemId: string): Promise<Cart> {
  const item = await prisma.cartItem.findUnique({
    where: { id: itemId }
  });

  if (!item) {
    throw new Error('Cart item not found');
  }

  return prisma.cart.update({
    where: { id: cartId },
    data: {
      items: {
        delete: { id: itemId }
      },
      total: {
        decrement: item.price * item.quantity
      }
    },
    include: {
      items: true
    }
  });
}