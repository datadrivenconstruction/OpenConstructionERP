export { Button } from './Button';
export type { ButtonProps } from './Button';

export { FileTypeChips } from './FileTypeChips';
export type { FileTypeChipsProps } from './FileTypeChips';

export { AIDisclaimerBanner } from './AIDisclaimerBanner';

export { BetaBanner } from './BetaBanner';
export type { BetaBannerProps } from './BetaBanner';

export { PartnerLogoBadge } from './PartnerLogoBadge';

export { Input } from './Input';
export type { InputProps } from './Input';

export { Badge } from './Badge';

export { Card, CardHeader, CardContent, CardFooter } from './Card';

export { StatCard } from './StatCard';
export type { StatCardProps, StatCardTone } from './StatCard';

export { EmptyState } from './EmptyState';
export type { EmptyStateProps } from './EmptyState';

export { RecoveryCard } from './RecoveryCard';
export type { RecoveryCardProps } from './RecoveryCard';

export { AuthImage } from './AuthImage';
export type { AuthImageProps } from './AuthImage';

export { Skeleton, SkeletonText } from './Skeleton';

export {
  SkeletonText as SkeletonLine,
  SkeletonCard,
  SkeletonTable,
  SkeletonGrid,
} from './SkeletonLoader';
export type {
  SkeletonTextProps as SkeletonLineProps,
  SkeletonCardProps,
  SkeletonTableProps,
  SkeletonGridProps,
} from './SkeletonLoader';

export { StatusDot } from './StatusDot';

export { Logo, LogoWithText } from './Logo';

export { ShortcutsDialog } from './ShortcutsDialog';

export { Toast } from './Toast';

export { ToastContainer } from './ToastContainer';

export { BackgroundInstallBanner } from './BackgroundInstallBanner';

export { CommandPalette } from './CommandPalette';

export { InfoHint } from './InfoHint';

export { DismissibleInfo, IntroRichText } from './DismissibleInfo';
export type { DismissibleInfoLink } from './DismissibleInfo';

// Guidance primitives (clarity plan, Wave 0) — one shared way to explain
// AI confidence, AI suggestions, errors, and jargon across every module.
export { ConfidenceBadge, bandForScore, CONFIDENCE_HIGH_MIN, CONFIDENCE_MEDIUM_MIN } from './ConfidenceBadge';
export type { ConfidenceBadgeProps, ConfidenceLevel } from './ConfidenceBadge';

export { SuggestionCard } from './SuggestionCard';
export type { SuggestionCardProps } from './SuggestionCard';

export { ErrorState } from './ErrorState';
export type { ErrorStateProps } from './ErrorState';

export { GlossaryTerm } from './GlossaryTerm';
export type { GlossaryTermProps } from './GlossaryTerm';

export { GridHeaderHelp } from './GridHeaderHelp';
export type { GridHeaderHelpParams } from './GridHeaderHelp';

export { PageHeader } from './PageHeader';
export type { PageHeaderProps } from './PageHeader';

export { FeedbackDialog } from './FeedbackDialog';

export { BOQPicker } from './BOQPicker';

export { ConfirmDialog } from './ConfirmDialog';
export type { ConfirmDialogProps } from './ConfirmDialog';

export { TabBar, tabIds } from './TabBar';
export type {
  TabBarTab,
  TabBarProps,
  TabBarVariant,
  TabBarSize,
} from './TabBar';

export { WideModal, WideModalSection, WideModalField } from './WideModal';
export type {
  WideModalProps,
  WideModalSectionProps,
  WideModalFieldProps,
  WideModalSize,
} from './WideModal';

export { SideDrawer } from './SideDrawer';
export type { SideDrawerProps } from './SideDrawer';

export { Breadcrumb } from './Breadcrumb';

export { ProjectMap, buildGeocodeQuery } from './ProjectMap';
export type { LatLng } from './ProjectMap';

export { ProjectWeather } from './ProjectWeather';
export type { BreadcrumbItem } from './Breadcrumb';

export { ErrorBoundary } from './ErrorBoundary';

export { NotFoundPage } from './NotFoundPage';

export { CountryFlag } from './CountryFlag';
export { CountryFlagBackdrop } from './CountryFlagBackdrop';

export { CountryCombobox, CUSTOM_SENTINEL } from './CountryCombobox';
export type { CountryComboboxProps } from './CountryCombobox';

export { OnboardingTour, DEFAULT_TOUR_STEPS, ONBOARDING_STORAGE_KEY } from './OnboardingTour';
export type { TourStep } from './OnboardingTour';

export {
  ProductTour,
  DEFAULT_PRODUCT_TOUR_STEPS,
  BOQ_TOUR_STEPS,
  ACCOMMODATION_TOUR_STEPS,
  TOUR_REGISTRY,
  TOUR_COMPLETED_KEY,
  TOUR_START_EVENT,
} from './ProductTour';
export type { ProductTourStep, ProductTourProps, TourId } from './ProductTour';

export { ModuleHelpButton } from './ModuleHelpButton';
export type { ModuleHelpButtonProps } from './ModuleHelpButton';

export { GlobalProgress, useProgressStore } from './GlobalProgress';

export { MoneyDisplay } from './MoneyDisplay';
export type { MoneyDisplayProps } from './MoneyDisplay';

export { DateDisplay } from './DateDisplay';
export type { DateDisplayProps } from './DateDisplay';

export { QuantityDisplay } from './QuantityDisplay';
export type { QuantityDisplayProps } from './QuantityDisplay';

export { NotificationBell } from './NotificationBell';

export { ActivityFeed } from './ActivityFeed';
export type { ActivityFeedProps } from './ActivityFeed';

export { CommentThread } from './CommentThread';
export type { CommentThreadProps } from './CommentThread';

export { GanttChart } from './Gantt';
export type { GanttProps, GanttActivity } from './Gantt';
export type { ViewMode as GanttViewMode } from './Gantt';

export { BIMViewer, DisciplineToggle } from './BIMViewer';
export type { BIMViewerProps, BIMViewMode } from './BIMViewer';

export { ViewInBIMButton } from './ViewInBIMButton';
export type { ViewInBIMButtonProps } from './ViewInBIMButton';

export { MiniGeometryPreview } from './MiniGeometryPreview';
export type { MiniGeometryPreviewProps } from './MiniGeometryPreview';

export { ContactSearchInput } from './ContactSearchInput';

export { ElementInfoPopover } from './ElementInfoPopover';
export type {
  ElementInfoPopoverProps,
  ElementPayload,
  BIMElementPayload,
  DWGElementPayload,
  PDFMeasurementPayload,
} from './ElementInfoPopover';

export { KvList, Kv } from './KvList';
export { QtyTile } from './QtyTile';

export { OfflineBanner } from './OfflineBanner';

export { PWAInstallPrompt } from './PWAInstallPrompt';

export { OfflineFallback, markLastSync } from './OfflineFallback';
