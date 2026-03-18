import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

interface AppLayoutProps {
  title?: string;
  children: ReactNode;
}

export function AppLayout({ title, children }: AppLayoutProps) {
  return (
    <div className="min-h-screen bg-surface-secondary">
      <Sidebar />
      <div className="pl-sidebar">
        <Header title={title} />
        <main className="p-6">{children}</main>
      </div>
    </div>
  );
}
