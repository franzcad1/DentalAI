import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'

let activeDriver: ReturnType<typeof driver> | null = null

export function destroyRecallTourIfActive() {
  if (activeDriver) {
    try { activeDriver.destroy() } catch {}
    activeDriver = null
  }
}

export function startRecallTour() {
  destroyRecallTourIfActive()
  const driverObj = driver({
    showProgress: true,
    animate: true,
    overlayColor: '#0f172a',
    overlayOpacity: 0.6,
    popoverClass: 'dentalai-tour-popover',
    steps: [
      {
        element: '[data-tour="recall-tabs"]',
        popover: {
          title: '🗂️ Status tabs',
          description: 'Switch between Pending, Contacted, Scheduled, and Dismissed to track where each patient is in the recall workflow.',
          side: 'bottom',
          align: 'start',
        },
      },
      {
        element: '[data-tour="recall-table"]',
        popover: {
          title: '📋 Recall list',
          description: 'Patients are sorted by how overdue they are. Red means 90+ days, amber is 30–90 days.',
          side: 'top',
          align: 'center',
        },
      },
      {
        element: '[data-tour="recall-actions"]',
        popover: {
          title: '⚡ Quick actions',
          description: 'Mark a patient as contacted, scheduled, or dismissed to move them through the workflow.',
          side: 'left',
          align: 'center',
        },
      },
      {
        element: '[data-tour="recall-ai-btn"]',
        popover: {
          title: '🤖 AI outreach draft',
          description: 'Click this button to have the AI write a personalised recall message for the patient — ready to copy and send.',
          side: 'left',
          align: 'center',
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
