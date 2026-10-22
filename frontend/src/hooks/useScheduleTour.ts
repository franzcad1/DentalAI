import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'

let activeDriver: ReturnType<typeof driver> | null = null

export function destroyTourIfActive() {
  if (activeDriver) {
    try { activeDriver.destroy() } catch {}
    activeDriver = null
  }
}

export function startScheduleTour(onCloseNewAppt?: () => void) {
  destroyTourIfActive()
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
          description: 'Each column is a provider. Appointments are stacked in their time slots. Scroll to see the full day.',
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
          onNextClick: () => {
            onCloseNewAppt?.()
            driverObj.moveNext()
          },
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
        element: '[data-tour="grid"]',
        popover: {
          title: '✋ Drag to reschedule',
          description: 'Click and drag any appointment block to move it to a different time or provider column. Give it a try — the tour will close when you start dragging.',
          side: 'top',
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
