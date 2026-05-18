#include <iostream>
#include <thread>
#include <mutex>
#include <vector>

// Shared state for the enrollment simulation
int seats = 30;
int enrolled = 0;
int waitlisted = 0;
std::mutex mtx;

void enroll_without_lock(int student_id) {
    // Intentionally unsafe: no locking
    if (seats > 0) {
        // widen the race window a bit
        seats--;
        enrolled++;
        std::cout << "[WITHOUT] thread=" << std::this_thread::get_id()
                  << " student=" << student_id
                  << " => seats=" << seats
                  << " enrolled=" << enrolled
                  << std::endl;
    } else {
        waitlisted++;
        std::cout << "[WITHOUT] thread=" << std::this_thread::get_id()
                  << " student=" << student_id
                  << " => WAITLISTED waitlisted=" << waitlisted
                  << std::endl;
    }
}

void enroll_with_lock(int student_id) {
    std::lock_guard<std::mutex> guard(mtx);

    if (seats > 0) {
        seats--;
        enrolled++;
        std::cout << "[WITH] thread=" << std::this_thread::get_id()
                  << " student=" << student_id
                  << " => seats=" << seats
                  << " enrolled=" << enrolled
                  << std::endl;
    } else {
        waitlisted++;
        std::cout << "[WITH] thread=" << std::this_thread::get_id()
                  << " student=" << student_id
                  << " => WAITLISTED waitlisted=" << waitlisted
                  << std::endl;
    }
}

int main() {
    const int total_students = 100;

    std::cout << "=== WITHOUT MUTEX LOCK ===" << std::endl;
    seats = 30;
    enrolled = 0;
    waitlisted = 0;

    std::vector<std::thread> threads;
    threads.reserve(total_students);

    for (int i = 0; i < total_students; i++) {
        threads.emplace_back(enroll_without_lock, i);
    }

    for (auto &t : threads) t.join();

    std::cout << "[WITHOUT] FINAL enrolled=" << enrolled
              << " waitlisted=" << waitlisted
              << " seats=" << seats
              << std::endl;

    std::cout << "\n=== WITH MUTEX LOCK ===" << std::endl;
    seats = 30;
    enrolled = 0;
    waitlisted = 0;

    threads.clear();
    threads.reserve(total_students);

    for (int i = 0; i < total_students; i++) {
        threads.emplace_back(enroll_with_lock, i);
    }

    for (auto &t : threads) t.join();

    std::cout << "[WITH] FINAL enrolled=" << enrolled
              << " waitlisted=" << waitlisted
              << " seats=" << seats
              << std::endl;

    return 0;
}

