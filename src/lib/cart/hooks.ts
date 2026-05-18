"use client";

import { useState, useCallback } from 'react';
import type { Cart, CartItem } from './types';

export function useCart() {
  const [cart, setCart] = useState<Cart | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCart = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/cart');
      if (!response.ok) throw new Error('Failed to fetch cart');
      const data = await response.json();
      setCart(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  const addItem = useCallback(async (item: Omit<CartItem, 'id'>) => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item)
      });
      if (!response.ok) throw new Error('Failed to add item');
      const data = await response.json();
      setCart(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  const updateItem = useCallback(async (itemId: string, quantity: number) => {
    if (!cart) return;
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/cart', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cartId: cart.id, itemId, quantity })
      });
      if (!response.ok) throw new Error('Failed to update item');
      const data = await response.json();
      setCart(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [cart]);

  const removeItem = useCallback(async (itemId: string) => {
    if (!cart) return;
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/cart', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cartId: cart.id, itemId })
      });
      if (!response.ok) throw new Error('Failed to remove item');
      const data = await response.json();
      setCart(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [cart]);

  return {
    cart,
    loading,
    error,
    fetchCart,
    addItem,
    updateItem,
    removeItem
  };
}