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

    /// Loads every event. Called from MapView on appear and after a new event
    /// is saved. When we care about geo filtering we'll swap this for an RPC
    /// that calls ST_DWithin server-side.
    static func fetchAll() async -> [Event] {
        do {
            let events: [Event] = try await SupabaseManager.shared
                .from("events")
                .select()
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
