//
//  VenueGroup.swift
//  Cityscape
//
//  Events that share one spot on the map, shown as a single pin.
//
//  Busy venues host many different events in a week (13 at Birdland, 10 at
//  Madison Square Garden), and every one of them carries the venue's exact
//  coordinates, so one Marker per event stacks them into a pile where only the
//  top pin can be tapped.
//
//  Grouping works on whatever list it is handed. A future time filter should
//  narrow the events first and group second; each pin then shows the next
//  event and count *within the filter* without any change here.
//

import Foundation
import CoreLocation

struct VenueGroup: Identifiable, Hashable {
    let id: String
    let coordinate: CLLocationCoordinate2D
    /// Sorted soonest first, so `events[0]` is what the pin is named after.
    let events: [Event]

    var nextEvent: Event { events[0] }

    /// Pin label: the next event, plus how many more are hidden behind it.
    var title: String {
        events.count == 1 ? nextEvent.name : "\(nextEvent.name) +\(events.count - 1)"
    }

    // Identity is the location alone. CLLocationCoordinate2D isn't Hashable,
    // and two groups at one spot can't exist anyway.
    static func == (lhs: VenueGroup, rhs: VenueGroup) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    /// Groups events by location. Coordinates are compared at 5 decimal places
    /// (about 1 m), so float noise can't split one venue in two, while venues
    /// across the street from each other stay separate.
    static func group(_ events: [Event]) -> [VenueGroup] {
        let byLocation = Dictionary(grouping: events) { event in
            String(format: "%.5f,%.5f", event.latitude, event.longitude)
        }
        return byLocation.map { key, events in
            let sorted = events.sorted { $0.startDate < $1.startDate }
            return VenueGroup(
                id: key,
                coordinate: CLLocationCoordinate2D(latitude: sorted[0].latitude,
                                                   longitude: sorted[0].longitude),
                events: sorted
            )
        }
    }
}
