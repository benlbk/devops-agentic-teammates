import { CartItem, CartSummary, CartEvent, CartEventType } from './types';

type CartEventListener = (event: CartEvent) => void;

class CartService {
  private items: CartItem[] = [];
  private listeners: CartEventListener[] = [];

  constructor() {
    this.loadFromStorage();
  }

  private loadFromStorage(): void {
    if (typeof window === 'undefined') return;
    
    const stored = localStorage.getItem('cart');
    if (stored) {
      try {
        this.items = JSON.parse(stored);
      } catch (error) {
        console.error('Failed to parse cart from storage:', error);
        this.items = [];
      }
    }
  }

  private saveToStorage(): void {
    if (typeof window === 'undefined') return;
    
    localStorage.setItem('cart', JSON.stringify(this.items));
  }

  private emitEvent(type: CartEventType, item?: CartItem): void {
    const event: CartEvent = { type, item };
    this.listeners.forEach(listener => listener(event));
  }

  public subscribe(listener: CartEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  public addItem(item: CartItem): void {
    const existingItem = this.items.find(i => i.id === item.id);
    
    if (existingItem) {
      existingItem.quantity += item.quantity;
    } else {
      this.items.push({ ...item });
    }

    this.saveToStorage();
    this.emitEvent('itemAdded', item);
  }

  public removeItem(itemId: string): void {
    const item = this.items.find(i => i.id === itemId);
    this.items = this.items.filter(i => i.id !== itemId);
    this.saveToStorage();
    if (item) {
      this.emitEvent('itemRemoved', item);
    }
  }

  public updateQuantity(itemId: string, quantity: number): void {
    const item = this.items.find(i => i.id === itemId);
    if (item) {
      item.quantity = Math.max(0, quantity);
      if (item.quantity === 0) {
        this.removeItem(itemId);
      } else {
        this.saveToStorage();
        this.emitEvent('quantityChanged', item);
      }
    }
  }

  public clearCart(): void {
    this.items = [];
    this.saveToStorage();
    this.emitEvent('cartCleared');
  }

  public getCartSummary(): CartSummary {
    const totalItems = this.items.reduce((sum, item) => sum + item.quantity, 0);
    const subtotal = this.items.reduce((sum, item) => sum + (item.price * item.quantity), 0);

    return {
      totalItems,
      subtotal,
      items: [...this.items]
    };
  }
}

// Singleton instance
export const cartService = new CartService();
