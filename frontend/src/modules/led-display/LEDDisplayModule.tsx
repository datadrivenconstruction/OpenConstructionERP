import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useState } from 'react';
import { MonitorPlay, Plus, Package, Wrench, FileText, DollarSign, Calendar, Activity } from 'lucide-react';

// Mock data for demonstration
const mockLEDProjects = [
  {
    id: '1',
    name: 'Building A Lobby Display',
    display_type: 'indoor',
    status: 'installation',
    screen_width_mm: 4000,
    screen_height_mm: 2000,
    installation_location: 'Main Lobby',
    planned_end_date: '2026-06-30',
    panels_count: 24,
    installation_progress_pct: 65,
  },
  {
    id: '2',
    name: 'Parking Garage Signage',
    display_type: 'outdoor',
    status: 'procurement',
    screen_width_mm: 6000,
    screen_height_mm: 3000,
    installation_location: 'Parking Level 1',
    planned_end_date: '2026-08-15',
    panels_count: 48,
    installation_progress_pct: 0,
  },
  {
    id: '3',
    name: 'Conference Room Video Wall',
    display_type: 'indoor',
    status: 'operational',
    screen_width_mm: 3000,
    screen_height_mm: 1700,
    installation_location: 'Conference Room B',
    planned_end_date: '2026-03-01',
    panels_count: 16,
    installation_progress_pct: 100,
  },
];

const statusColors: Record<string, string> = {
  planning: 'bg-blue-100 text-blue-800',
  procurement: 'bg-yellow-100 text-yellow-800',
  installation: 'bg-orange-100 text-orange-800',
  testing: 'bg-purple-100 text-purple-800',
  completed: 'bg-green-100 text-green-800',
  operational: 'bg-green-100 text-green-800',
  maintenance: 'bg-gray-100 text-gray-800',
};

const displayTypeLabels: Record<string, string> = {
  indoor: 'Indoor',
  outdoor: 'Outdoor',
  semi_outdoor: 'Semi-Outdoor',
  transparent: 'Transparent',
  curtain: 'Curtain',
  rental: 'Rental',
};

export default function LEDDisplayModule() {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const [activeTab, setActiveTab] = useState('overview');

  // If viewing a specific project
  if (projectId) {
    return <LEDProjectDetails projectId={projectId} />;
  }

  // List view
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-content-primary">{t('led.title', 'LED Display Projects')}</h1>
          <p className="text-sm text-content-tertiary mt-1">
            {t('led.create_first', 'Create your first LED display project to get started')}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
          <Plus className="h-4 w-4" />
          {t('led.new_project', 'New LED Project')}
        </button>
      </div>

      {mockLEDProjects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 border rounded-lg">
          <MonitorPlay className="h-12 w-12 text-content-tertiary mb-4" />
          <p className="text-content-tertiary">{t('led.no_projects', 'No LED projects found')}</p>
          <button className="mt-4 flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
            <Plus className="h-4 w-4" />
            {t('led.new_project', 'New LED Project')}
          </button>
        </div>
      ) : (
        <div className="grid gap-4">
          {mockLEDProjects.map((project) => (
            <div key={project.id} className="border rounded-lg p-6 hover:shadow-md transition-shadow cursor-pointer">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-primary/10 rounded-lg">
                    <MonitorPlay className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold">{project.name}</h3>
                    <div className="flex items-center gap-2 mt-1 text-sm text-content-tertiary">
                      <span>{displayTypeLabels[project.display_type]}</span>
                      <span>•</span>
                      <span>{project.screen_width_mm}x{project.screen_height_mm}mm</span>
                      <span>•</span>
                      <span>{project.installation_location}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-sm text-content-tertiary">
                      {project.panels_count} {t('led.panels', 'panels')}
                    </div>
                    <div className="mt-1">
                      <div className="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-primary"
                          style={{ width: `${project.installation_progress_pct}%` }}
                        />
                      </div>
                      <div className="text-xs text-content-tertiary mt-1">
                        {project.installation_progress_pct}% {t('led.installation', 'installation')}
                      </div>
                    </div>
                  </div>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[project.status]}`}>
                    {t(`led.${project.status}`, project.status)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LEDProjectDetails({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  
  // Mock stats
  const stats = {
    totalPanels: 24,
    installedPanels: 18,
    operationalPanels: 16,
    damagedPanels: 1,
    totalControllers: 4,
    operationalControllers: 3,
    faultyControllers: 1,
    totalBudget: '45,000',
    spentBudget: '32,500',
    remainingBudget: '12,500',
    completedMilestones: 3,
    pendingMilestones: 4,
    installationProgressPct: 65,
    maintenanceLogsCount: 5,
    upcomingMaintenance: 2,
    documentsCount: 12,
  };

  const [activeTab, setActiveTab] = useState('overview');

  const tabs = [
    { id: 'overview', label: t('led.status', 'Status') },
    { id: 'panels', label: t('led.panels', 'Panels') },
    { id: 'controllers', label: t('led.controllers', 'Controllers') },
    { id: 'inventory', label: t('led.inventory', 'Inventory') },
    { id: 'milestones', label: t('led.milestones', 'Milestones') },
    { id: 'maintenance', label: t('led.maintenance_logs', 'Maintenance') },
    { id: 'documents', label: t('led.documents', 'Documents') },
    { id: 'budget', label: t('led.budget', 'Budget') },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-content-primary">Building A Lobby Display</h1>
          <div className="flex items-center gap-3 mt-2 text-content-tertiary">
            <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors.installation}`}>
              {t('led.installation', 'Installation')}
            </span>
            <span>Indoor LED Display</span>
            <span>•</span>
            <span>4000 x 2000mm</span>
          </div>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
          <Plus className="h-4 w-4" />
          {t('led.new_project', 'New LED Project')}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-tertiary">{t('led.total_panels', 'Total Panels')}</span>
            <Package className="h-4 w-4 text-content-tertiary" />
          </div>
          <div className="text-2xl font-bold mt-2">{stats.totalPanels}</div>
          <p className="text-xs text-content-tertiary mt-1">
            {stats.installedPanels} installed, {stats.operationalPanels} operational
          </p>
        </div>
        <div className="border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-tertiary">{t('led.total_controllers', 'Total Controllers')}</span>
            <Activity className="h-4 w-4 text-content-tertiary" />
          </div>
          <div className="text-2xl font-bold mt-2">{stats.totalControllers}</div>
          <p className="text-xs text-content-tertiary mt-1">
            {stats.operationalControllers} operational, {stats.faultyControllers} faulty
          </p>
        </div>
        <div className="border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-tertiary">{t('led.budget_total', 'Total Budget')}</span>
            <DollarSign className="h-4 w-4 text-content-tertiary" />
          </div>
          <div className="text-2xl font-bold mt-2">€{stats.totalBudget}</div>
          <p className="text-xs text-content-tertiary mt-1">
            €{stats.spentBudget} spent, €{stats.remainingBudget} remaining
          </p>
        </div>
        <div className="border rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-tertiary">{t('led.progress', 'Progress')}</span>
            <Calendar className="h-4 w-4 text-content-tertiary" />
          </div>
          <div className="text-2xl font-bold mt-2">{stats.installationProgressPct}%</div>
          <p className="text-xs text-content-tertiary mt-1">
            {stats.completedMilestones}/{stats.completedMilestones + stats.pendingMilestones} milestones
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b">
        <div className="flex gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-content-tertiary hover:text-content-primary'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-4">{t('led.stats', 'Project Statistics')}</h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-content-tertiary">{t('led.installation_progress', 'Installation Progress')}</span>
                <span className="font-medium">{stats.installationProgressPct}%</span>
              </div>
              <div className="w-full h-2 bg-gray-200 rounded-full">
                <div className="h-2 bg-primary rounded-full" style={{ width: `${stats.installationProgressPct}%` }} />
              </div>
            </div>
          </div>
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-4">{t('led.upcoming_maintenance', 'Upcoming Maintenance')}</h3>
            <p className="text-content-tertiary">{stats.upcomingMaintenance} scheduled</p>
          </div>
        </div>
      )}

      {activeTab === 'panels' && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium">Panel ID</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Manufacturer</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Model</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Position</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-4 py-3">PANEL-001</td>
                <td className="px-4 py-3">Barco</td>
                <td className="px-4 py-3">XT-4</td>
                <td className="px-4 py-3">Row 1, Col 1</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">operational</span></td>
              </tr>
              <tr className="border-t">
                <td className="px-4 py-3">PANEL-002</td>
                <td className="px-4 py-3">Barco</td>
                <td className="px-4 py-3">XT-4</td>
                <td className="px-4 py-3">Row 1, Col 2</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">operational</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'controllers' && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium">Controller ID</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Type</th>
                <th className="px-4 py-3 text-left text-sm font-medium">IP Address</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-4 py-3">CTRL-001</td>
                <td className="px-4 py-3">Sending Card</td>
                <td className="px-4 py-3">192.168.1.100</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">operational</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'milestones' && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium">Name</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Type</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Planned Date</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-4 py-3">Procurement Complete</td>
                <td className="px-4 py-3">Procurement</td>
                <td className="px-4 py-3">2026-04-15</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">completed</span></td>
              </tr>
              <tr className="border-t">
                <td className="px-4 py-3">Structural Installation</td>
                <td className="px-4 py-3">Installation</td>
                <td className="px-4 py-3">2026-05-30</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-orange-100 text-orange-800 rounded text-xs">in_progress</span></td>
              </tr>
              <tr className="border-t">
                <td className="px-4 py-3">Electrical Connection</td>
                <td className="px-4 py-3">Electrical</td>
                <td className="px-4 py-3">2026-06-15</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-gray-100 text-gray-800 rounded text-xs">pending</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'maintenance' && (
        <div className="border rounded-lg p-8 text-center">
          <Wrench className="h-12 w-12 mx-auto text-content-tertiary opacity-50 mb-4" />
          <p className="text-content-tertiary">{t('led.no_projects', 'No maintenance records yet')}</p>
        </div>
      )}

      {activeTab === 'documents' && (
        <div className="border rounded-lg p-8 text-center">
          <FileText className="h-12 w-12 mx-auto text-content-tertiary opacity-50 mb-4" />
          <p className="text-content-tertiary">{t('led.no_projects', 'No documents yet')}</p>
        </div>
      )}

      {activeTab === 'budget' && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium">Category</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Planned</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Actual</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-4 py-3">Hardware</td>
                <td className="px-4 py-3">€30,000</td>
                <td className="px-4 py-3">€28,500</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">under budget</span></td>
              </tr>
              <tr className="border-t">
                <td className="px-4 py-3">Installation</td>
                <td className="px-4 py-3">€10,000</td>
                <td className="px-4 py-3">€4,000</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">in_progress</span></td>
              </tr>
              <tr className="border-t">
                <td className="px-4 py-3">Contingency</td>
                <td className="px-4 py-3">€5,000</td>
                <td className="px-4 py-3">€0</td>
                <td className="px-4 py-3"><span className="px-2 py-1 bg-gray-100 text-gray-800 rounded text-xs">planned</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'inventory' && (
        <div className="border rounded-lg p-8 text-center">
          <Package className="h-12 w-12 mx-auto text-content-tertiary opacity-50 mb-4" />
          <p className="text-content-tertiary">{t('led.no_projects', 'No inventory items yet')}</p>
        </div>
      )}
    </div>
  );
}