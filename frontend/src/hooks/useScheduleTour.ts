import { driver, Driver } from 'driver.js'
import 'driver.js/dist/driver.css'

let activeDriver: Driver | null = null

export function destroyActiveTour() {
  if (activeDriver) { activeDriver.destroy(); activeDriver = null }
}

export function startScheduleTour() {
  destroyActiveTour()
  const driverObj = driver({
    showProgress: true,
    animate: true,
    overlayColor: '#0f172a',
    overlayOpacity: 0.6,
    popoverClass: 'dentalai-tour-popover',
    steps: [
      {
        element: '[data-tour="grid"]',
        popover: {
          title: '📅 Calendar grid',
          description: 'Each column is a provider. Appointments are stacked in their time slots. Scroll to see the full day. Click any empty slot to open a pre-filled booking form.',
          side: 'top',
          align: 'center',
        },
      },
      {
        element: '[data-tour="grid"]',
        popover: {
          title: '✋ Drag to reschedule',
          description: 'Click and drag any appointment block to move it to a different time or a different provider column.',
          side: 'top',
          align: 'center',
        },
      },
      {
        element: '[data-tour="grid"]',
        popover: {
          title: '↕ Extend the length',
          description: 'Grab the thin handle at the bottom of any appointment block to make it longer or shorter.',
          side: 'top',
          align: 'center',
        },
      },
      {
        element: '[data-tour="new-appt-btn"]',
        popover: {
          title: '📋 New Appointment button',
          description: 'Use this button at the top to book a new appointment from scratch.',
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
