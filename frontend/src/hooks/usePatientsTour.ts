import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'

let activeDriver: ReturnType<typeof driver> | null = null

export function destroyPatientsTourIfActive() {
  if (activeDriver) {
    try { activeDriver.destroy() } catch {}
    activeDriver = null
  }
}

export function startPatientsTour() {
  destroyPatientsTourIfActive()
  const driverObj = driver({
    showProgress: true,
    animate: true,
    overlayColor: '#0f172a',
    overlayOpacity: 0.6,
    popoverClass: 'dentalai-tour-popover',
    steps: [
      {
        element: '[data-tour="patients-search"]',
        popover: {
          title: '🔍 Search patients',
          description: 'Type a name to instantly filter the list.',
          side: 'bottom',
          align: 'start',
        },
      },
      {
        element: '[data-tour="patients-table"]',
        popover: {
          title: '👥 Patient list',
          description: 'Click any row to open the patient detail panel — appointment history, recall status, and a quick booking shortcut.',
          side: 'top',
          align: 'center',
        },
      },
      {
        element: '[data-tour="patients-add"]',
        popover: {
          title: '➕ Add patient',
          description: 'Register a new patient with their name, DOB, email and phone.',
          side: 'bottom',
          align: 'end',
        },
      },
    ],
    onDestroyStarted: () => {
      activeDriver = null
      driverObj.destroy()
    },
  })
  activeDriver = driverObj
  driverObj.drive()
}
