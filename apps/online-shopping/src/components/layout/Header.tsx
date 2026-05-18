import Link from 'next/link';
import SearchBar from './SearchBar';
import CartIcon from './CartIcon';

export default function Header() {
  return (
    <header className="bg-white shadow-md">
      <div className="container mx-auto px-4 py-4 flex items-center justify-between">
        <Link href="/" className="text-2xl font-bold text-gray-800">
          Shop
        </Link>
        <SearchBar />
        <nav className="flex items-center gap-6">
          <Link href="/categories" className="text-gray-600 hover:text-gray-900">
            Categories
          </Link>
          <Link href="/account" className="text-gray-600 hover:text-gray-900">
            Account
          </Link>
          <CartIcon />
        </nav>
      </div>
    </header>
  );
}
