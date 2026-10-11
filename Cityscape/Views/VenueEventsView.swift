//
//  VenueEventsView.swift
//  Cityscape
//
//  The list shown when a pin holds more than one event.
//

import SwiftUI

struct VenueEventsView: View {
    let group: VenueGroup

    var body: some View {
        List(group.events) { event in
            NavigationLink {
                DetailView(event: event)
            } label: {
                HStack {
                    Image(systemName: event.eventType?.iconName ?? "mappin.circle")
                        .foregroundStyle(Color("cityscapePrimary"))
                    VStack(alignment: .leading) {
                        Text(event.name)
                            .font(.headline)
                            .foregroundStyle(Color("cityscapeSecondary"))
                        Text(event.startDate.formatted(date: .abbreviated, time: .shortened))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .listStyle(.plain)
        .navigationTitle("\(group.events.count) events here")
        .navigationBarTitleDisplayMode(.inline)
    }
}
