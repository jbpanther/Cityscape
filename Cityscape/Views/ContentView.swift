//
//  MapView.swift
//  Cityscape
//
//  Created by Jackson Butler on 10/8/25.
//  Rewritten during Phase C of the Firebase → Supabase migration.
//

import SwiftUI
import MapKit
import Supabase

enum ActiveSheet: Identifiable {
    case bottom
    case create

    var id: Int {
        switch self {
        case .bottom: return 0
        case .create: return 1
        }
    }
}

struct MapView: View {

    // Events are loaded once on appear and re-loaded whenever the create-event
    // sheet closes. If we want live updates later, swap this for a Supabase
    // Realtime subscription — the shape of `events` doesn't need to change.
    @State private var events: [Event] = []

    @State private var defaultEnable = true
    @State private var activeSheet: ActiveSheet? = .bottom
    @State private var lastPresentedSheet: ActiveSheet? = .bottom
    @State private var bottomSheetDetent: PresentationDetent = .fraction(0.35)
    @State var locationManager = LocationManager()
    @State private var cameraPosition: MapCameraPosition = .userLocation(fallback: .automatic)
    @State private var selectedEvent: Event?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {

            ZStack {

                Map(position: $cameraPosition, selection: $selectedEvent) {
                    ForEach(events) { event in

                        let coordinate = CLLocationCoordinate2D(latitude: event.latitude,
                                                                longitude: event.longitude)
                        Marker(event.name,
                               systemImage: event.eventType?.iconName ?? "mappin.circle",
                               coordinate: coordinate)
                            .tag(event)
                    }
                    .tint(Color("cityscapePrimary"))

                    UserAnnotation()
                }
                .mapControls({
                    MapUserLocationButton()
                    MapCompass()
                })
                .mapStyle(.standard(pointsOfInterest: .including([.aquarium,.amusementPark,.beach,.bowling,.brewery,.museum,.zoo,.castle,.distillery,.landmark,.musicVenue,.publicTransport,.stadium,.winery])))
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Sign Out") {
                            Task {
                                do {
                                    try await SupabaseManager.shared.auth.signOut()
                                    print("Sign out successful")
                                    dismiss()
                                } catch {
                                    print("ERROR: Could not sign out: \(error.localizedDescription)")
                                }
                            }
                        }
                    }
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            activeSheet = .create
                            lastPresentedSheet = .create
                        } label: {
                            Image(systemName: "plus.circle")
                        }
                    }
                }
            }
            .navigationDestination(item: $selectedEvent) { event in
                DetailView(event: event)
            }
            .sheet(item: $activeSheet, onDismiss: {
                // When the create sheet dismisses, reload events so any new
                // one shows up, then restore the bottom sheet.
                if lastPresentedSheet == .create {
                    Task { await loadEvents() }
                    activeSheet = .bottom
                    lastPresentedSheet = .bottom
                }
            }) { sheet in
                switch sheet {
                case .bottom:
                    BottomSheetView(events: events,
                                    userLocation: locationManager.location?.coordinate) { event in
                        let coord = CLLocationCoordinate2D(latitude: event.latitude,
                                                           longitude: event.longitude)

                        withAnimation {
                            cameraPosition = .region(
                                MKCoordinateRegion(
                                    center: coord,
                                    latitudinalMeters: 1000,
                                    longitudinalMeters: 1000
                                )
                            )
                        }
                    }
                    .presentationDetents(
                        [.fraction(0.18), .fraction(0.35), .large],
                        selection: $bottomSheetDetent
                    )
                    .presentationDragIndicator(.visible)
                    .interactiveDismissDisabled()
                    .presentationBackgroundInteraction(.enabled)

                case .create:
                    NavigationStack {
                        CustomEventView(event: Event())
                    }
                }
            }
            .onChange(of: selectedEvent) { _, newValue in
                if newValue != nil {
                    activeSheet = nil
                } else {
                    activeSheet = .bottom
                    lastPresentedSheet = .bottom
                }
            }
            .task {
                await loadEvents()
            }
            .onAppear {
                activeSheet = .bottom
                lastPresentedSheet = .bottom
            }
        }
    }

    private func loadEvents() async {
        events = await EventViewModel.fetchAll()
    }
}


struct BottomSheetView: View {

    let events: [Event]
    let userLocation: CLLocationCoordinate2D?
    var onEventSelected: (Event) -> Void

    @State private var searchText = ""

    private var sortedEvents: [Event] {
        guard let userLocation else { return events }

        let userLoc = CLLocation(latitude: userLocation.latitude,
                                 longitude: userLocation.longitude)

        return events.sorted { e1, e2 in
            let loc1 = CLLocation(latitude: e1.latitude, longitude: e1.longitude)
            let loc2 = CLLocation(latitude: e2.latitude, longitude: e2.longitude)
            return userLoc.distance(from: loc1) < userLoc.distance(from: loc2)
        }
    }

    private var visibleEvents: [Event] {
        let base = sortedEvents
        guard !searchText.isEmpty else { return base }
        return base.filter { event in
            event.name.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(spacing: 12) {
            Capsule()
                .frame(width: 40, height: 5)
                .foregroundStyle(.secondary)
                .padding(.top, 8)

            HStack {
                Image(systemName: "magnifyingglass")
                TextField("Search for Event", text: $searchText)
                    .foregroundColor(.secondary)
                Spacer()
            }
            .padding(10)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.thinMaterial)
            )
            .padding(.horizontal)

            List {
                Section(header: Text("Nearby Events")) {
                    ForEach(visibleEvents) { event in
                        HStack {
                            Image(systemName: event.eventType?.iconName ?? "mappin.circle")
                                .foregroundStyle(Color("cityscapePrimary"))
                            VStack(alignment: .leading) {
                                Text(event.name)
                                    .font(.headline)
                                    .foregroundStyle(Color("cityscapeSecondary"))
                                Text("Until \(event.endDate.formatted(date: .abbreviated, time: .shortened))")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture {
                            onEventSelected(event)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .searchable(text: $searchText)
        }
        .padding(.bottom, 8)
    }
}

#Preview {
    MapView()
}
