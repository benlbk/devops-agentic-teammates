'use client';

import { useState, useEffect } from 'react';
import { cartService } from '@/lib/cart/cartService';
import { CartSummary, CartEvent } from '@/lib/cart/types';

export function useCart() {
  const [cartSummary, setCartSummary] = useState<CartSummary>(cartService.getCartSummary());

  useEffect(() => {
    const unsubscribe = cartService.subscribe((event: CartEvent) => {
      setCartSummary(cartService.getCartSummary());
    });

    return () => {
      unsubscribe();
    };
  }, []);

  return {
    ...cartSummary,
    addItem: cartService.addItem.bind(cartService),
    removeItem: cartService.removeItem.bind(cartService),
    updateQuantity: cartService.updateQuantity.bind(cartService),
    clearCart: cartService.clearCart.bind(cartService)
  };
}
