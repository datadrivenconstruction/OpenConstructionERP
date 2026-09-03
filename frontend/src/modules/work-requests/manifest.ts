// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { ClipboardList } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const WorkRequestsPage = lazy(() => import('./WorkRequestsPage')) as unknown as LazyExoticComponent<ComponentType<unknown>>;
const RequestDetailPage = lazy(() => import('./RequestDetailPage')) as unknown as LazyExoticComponent<ComponentType<unknown>>;
const ManageDepartmentsPage = lazy(() => import('./ManageDepartmentsPage')) as unknown as LazyExoticComponent<ComponentType<unknown>>;

export const manifest: ModuleManifest = {
  id: 'work-requests',
  name: 'modules.work_requests.name',
  description: 'modules.work_requests.description',
  version: '0.1.0',
  icon: ClipboardList,
  category: 'planning',
  defaultEnabled: true,
  routes: [
    { path: '/work-requests', title: 'nav.work_requests', component: WorkRequestsPage },
    // Before `/:requestId`, or "departments" would be read as a request id.
    { path: '/work-requests/departments', title: 'wr.manage_title', component: ManageDepartmentsPage },
    { path: '/work-requests/:requestId', title: 'wr.request_title', component: RequestDetailPage },
    { path: '/projects/:projectId/work-requests', title: 'nav.work_requests', component: WorkRequestsPage },
  ],
  navItems: [
    {
      // Overview, directly under Team metrics: the PM's daily "what do I
      // need from the workshop / drafting / HA" screen.
      labelKey: 'nav.work_requests',
      to: '/work-requests',
      icon: ClipboardList,
      group: 'grp_overview',
      advancedOnly: false,
    },
  ],
  translations: {
    en: {
      'modules.work_requests.name': 'Work Requests',
      'modules.work_requests.description':
        'Cross-department intake and tracking - a PM asks the workshop, drafting or hazardous-area team for work; each department tracks it through its own stages with hours, dates and a headcount planner',
      'nav.work_requests': 'Work requests',
      'wr.request_title': 'Work request',
      'wr.manage_title': 'Manage departments',
    },
    de: {
      'modules.work_requests.name': 'Arbeitsanfragen',
      'modules.work_requests.description':
        'Abteilungsübergreifende Anfragen und Verfolgung - ein PM fordert Arbeit von Werkstatt, Zeichnungsbüro oder Ex-Bereich an; jede Abteilung verfolgt sie in eigenen Phasen mit Stunden, Terminen und Personalplanung',
      'nav.work_requests': 'Arbeitsanfragen',
      'wr.request_title': 'Arbeitsanfrage',
      'wr.manage_title': 'Abteilungen verwalten',
    },
    fr: {
      'modules.work_requests.name': 'Demandes de travaux',
      'modules.work_requests.description':
        'Demandes inter-services et suivi - un chef de projet sollicite l’atelier, le bureau d’études ou l’équipe zones dangereuses ; chaque service suit ses propres étapes avec heures, dates et planning des effectifs',
      'nav.work_requests': 'Demandes de travaux',
      'wr.request_title': 'Demande de travaux',
      'wr.manage_title': 'Gérer les services',
    },
    ru: {
      'modules.work_requests.name': 'Заявки на работы',
      'modules.work_requests.description':
        'Межотдельные заявки и контроль - ПМ запрашивает работу у цеха, чертёжников или группы взрывоопасных зон; каждый отдел ведёт её по своим этапам с часами, сроками и планом численности',
      'nav.work_requests': 'Заявки на работы',
      'wr.request_title': 'Заявка на работы',
      'wr.manage_title': 'Управление отделами',
    },
  },
};
