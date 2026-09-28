//
//  EventViewModel.swift
//  Cityscape
//
//  Created by Jackson Butler on 12/1/25.
//  Rewritten during Phase C of the Firebase → Supabase migration.
//

import Foundation
import Supabase

@Observable
class EventViewModel {

    /// Inserts a new event or updates an existing one. Returns the id of the
    /// saved event (as a String, to keep the CustomEventView save flow
    /// unchanged from the Firestore era) or nil on failure.
    static func saveEvent(event: Event) async -> String? {
        let client = SupabaseManager.shared

        // Any write requires a logged-in user because Row-Level Security
        // policies check auth.uid() against created_by.
        guard let userId = client.auth.currentUser?.id else {
            print("ERROR: saveEvent called with no logged-in Supabase user")
            return nil
        }

        do {
            if let existingId = event.id {
                // Update path: send only the fields the user can edit.
                let payload = EventInsert(from: event, userId: userId)
                try await client
                    .from("events")
                    .update(payload)
                    .eq("id", value: existingId)
                    .execute()
                print("Event updated: \(existingId)")
                return existingId.uuidString
            } else {
                // Insert path: strip DB-managed fields and get the new row back.
                let payload = EventInsert(from: event, userId: userId)
                let inserted: Event = try await client
                    .from("events")
                    .insert(payload, returning: .representation)
                    .select()
                    .single()
                    .execute()
                    .value
                print("Event inserted: \(inserted.id?.uuidString ?? "?")")
                return inserted.id?.uuidString
            }
        } catch {
            print("ERROR saving event: \(error.localizedDescription)")
            return nil
        }
    }

    static func deleteEvent(event: Event) {
        guard let id = event.id else {
            print("ERROR: Tried to delete event with no ID")
            return
        }

        Task {
            do {
                try await SupabaseManager.shared
                    .from("events")
                    .delete()
                    .eq("id", value: id)
                    .execute()
                print("Event deleted: \(id)")
            } catch {
                print("ERROR deleting event: \(error.localizedDescription)")
            }
        }
    }

    /// How far ahead the map looks by default. Scraped ingestion puts roughly
    /// 40 events a day into NYC alone, so an unbounded fetch would return over a
    /// thousand pins and bury the map. A week is enough to feel alive without
    /// becoming noise.
    static let defaultHorizonDays = 7

    /// Loads the events the map should currently show: anything not yet over,
    /// starting within the next `daysAhead` days. Called from MapView on appear
    /// and after a new event is saved.
    ///
    /// Note the two bounds do different jobs:
    ///
    ///   - `end_at >= now` filters out events that have finished. It is
    ///     deliberately NOT `start_at >= now`, because a multi-day event that is
    ///     currently mid-run should still appear on the map — filtering on the
    ///     start date would make a weekend festival vanish the moment it opened.
    ///   - `start_at <= now + daysAhead` keeps the far future out of the way.
    ///
    /// When we care about geo filtering we'll swap this for an RPC that calls
    /// ST_DWithin server-side; the time window should move into that RPC too.
    static func fetchUpcoming(daysAhead: Int = defaultHorizonDays) async -> [Event] {
        // Supabase compares these as timestamptz, so they must be sent as
        // ISO-8601 with an explicit offset — not localized description strings.
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone(secondsFromGMT: 0)

        let now = Date()
        let horizon = Calendar.current.date(byAdding: .day, value: daysAhead, to: now) ?? now

        do {
            let events: [Event] = try await SupabaseManager.shared
                .from("events")
                .select()
                .gte("end_at", value: formatter.string(from: now))
                .lte("start_at", value: formatter.string(from: horizon))
                .order("start_at", ascending: true)
                .execute()
                .value
            return events
        } catch {
            print("ERROR fetching events: \(error.localizedDescription)")
            return []
        }
    }
}
