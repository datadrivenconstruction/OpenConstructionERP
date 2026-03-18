import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardContent, Button, Badge } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useAuthStore } from '@/stores/useAuthStore';

interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: string;
  locale: string;
  is_active: boolean;
  created_at: string;
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const logout = useAuthStore((s) => s.logout);

  const { data: profile } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<UserProfile>('/v1/users/me'),
    retry: false,
  });

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="animate-card-in" style={{ animationDelay: '0ms' }}>
        <h1 className="text-2xl font-bold text-content-primary">{t('nav.settings', 'Settings')}</h1>
        <p className="mt-1 text-sm text-content-secondary">Manage your account and preferences</p>
      </div>

      {/* Profile */}
      <Card className="animate-card-in" style={{ animationDelay: '100ms' }}>
        <CardHeader title="Profile" subtitle="Your personal information" />
        <CardContent>
          {profile ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-oe-blue text-xl font-bold text-white">
                  {profile.full_name?.charAt(0)?.toUpperCase() || 'U'}
                </div>
                <div>
                  <div className="text-base font-semibold text-content-primary">{profile.full_name}</div>
                  <div className="text-sm text-content-secondary">{profile.email}</div>
                  <Badge variant="blue" size="sm" className="mt-1">{profile.role}</Badge>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border-light">
                <div>
                  <span className="text-xs text-content-tertiary">Member since</span>
                  <div className="text-sm text-content-primary">{new Date(profile.created_at).toLocaleDateString()}</div>
                </div>
                <div>
                  <span className="text-xs text-content-tertiary">Status</span>
                  <div><Badge variant={profile.is_active ? 'success' : 'error'} size="sm" dot>{profile.is_active ? 'Active' : 'Inactive'}</Badge></div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-content-secondary">Loading profile...</p>
          )}
        </CardContent>
      </Card>

      {/* Language */}
      <Card className="animate-card-in" style={{ animationDelay: '200ms' }}>
        <CardHeader title="Language & Region" subtitle="Choose your preferred language" />
        <CardContent>
          <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isActive = i18n.language === lang.code;
              return (
                <button
                  key={lang.code}
                  onClick={() => i18n.changeLanguage(lang.code)}
                  className={`flex flex-col items-center gap-1 rounded-xl px-3 py-3 text-center transition-all duration-normal ease-oe ${
                    isActive
                      ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue'
                      : 'border-2 border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  <span className="text-lg">{lang.flag}</span>
                  <span className="text-2xs font-medium truncate w-full">{lang.name}</span>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Danger zone */}
      <Card className="animate-card-in border-semantic-error/20" style={{ animationDelay: '300ms' }}>
        <CardHeader title="Account" subtitle="Sign out or manage your account" />
        <CardContent>
          <Button
            variant="danger"
            onClick={() => { logout(); window.location.href = '/login'; }}
          >
            Sign Out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
